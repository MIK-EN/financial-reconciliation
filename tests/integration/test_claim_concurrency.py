"""Two accounts racing for one guest result must have exactly one owner."""

from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, text
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api.dependencies import get_db
from english_for_developers.storage.models import BrowserSession, OnboardingRun, OnboardingStep
from tests.integration import test_registration as registration

claim_client = registration.registration_client


def _snapshot(engine: Engine) -> list[list[dict]]:
    with Session(engine) as db:
        rows = registration._snapshot(db)
        rows.append(
            list(db.execute(select(*OnboardingStep.__table__.columns).order_by(OnboardingStep.id)))
        )
        return [[dict(row._mapping) for row in table] for table in rows]


@pytest.mark.parametrize("guest_position", ["first", "middle", "last"])
def test_two_accounts_claim_one_guest_result(
    claim_client: TestClient, test_engine: Engine, guest_position: str
) -> None:
    ready = Barrier(3, timeout=10)
    backend_pids: Queue[int] = Queue()
    session_lock_holders: Queue[int] = Queue()
    loser_paused = Event()
    release_loser = Event()

    def concurrent_db() -> Iterator[Session]:
        # Each HTTP request owns its Session and PostgreSQL connection.
        with Session(test_engine) as db:

            @event.listens_for(db, "after_begin")
            def start_together(session, transaction, connection):
                connection.exec_driver_sql("SET LOCAL lock_timeout = '12s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
                pid = connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
                backend_pids.put(pid)
                ready.wait()

            @event.listens_for(db, "do_orm_execute", retval=True)
            def pause_second_session_holder(execution):
                result = execution.invoke_statement()
                if (
                    execution.is_select
                    and execution.statement.column_descriptions[0].get("entity") is BrowserSession
                ):
                    # The real SELECT has acquired the shared guest lock. Its
                    # second holder can only arrive after the first committed.
                    session_lock_holders.put(1)
                    if session_lock_holders.qsize() == 2:
                        loser_paused.set()
                        assert release_loser.wait(10), "Loser was not released"
                return result

            yield db

    with TestClient(claim_client.app, base_url="http://testserver") as other:
        clients = [claim_client, other]
        accounts = []
        old_states = []
        for index, client in enumerate(clients):
            headers, state = registration._complete(client)
            response = client.post(
                "/api/v1/auth/register",
                headers=headers,
                json={
                    "username": f"reader_{index}",
                    "password": registration.PASSWORD,
                    "run_id": state["id"],
                },
            )
            assert response.status_code == 201
            accounts.append(response.json())
            old_states.append(client.get(f"/api/v1/onboarding/{state['id']}").json())
            client.cookies.delete("eds_session_dev")

        _, state = registration._complete(claim_client)
        guest_token = claim_client.cookies["eds_session_dev"]
        other.cookies.update({"eds_session_dev": guest_token})
        assert clients[0].cookies["eds_auth_dev"] != clients[1].cookies["eds_auth_dev"]
        with Session(test_engine) as db:
            auths = db.scalars(
                select(BrowserSession)
                .where(BrowserSession.kind == "authenticated")
                .order_by(BrowserSession.user_id)
            ).all()
            guest = db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash == hash_session_token(guest_token)
                )
            )
            assert guest is not None
            guest_id = guest.id
            offsets = {"first": (1, 2), "middle": (-1, 1), "last": (-2, -1)}[guest_position]
            for auth, offset in zip(auths, offsets, strict=True):
                auth.id = UUID(int=guest_id.int + offset)
            db.commit()

        before = _snapshot(test_engine)
        run_id = UUID(state["id"])
        claim_client.app.dependency_overrides[get_db] = concurrent_db
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                with Session(test_engine) as blocker:
                    blocker.execute(text("SET LOCAL statement_timeout = '15s'"))
                    blocker_pid = blocker.scalar(text("SELECT pg_backend_pid()"))
                    blocker.scalar(
                        select(OnboardingRun).where(OnboardingRun.id == run_id).with_for_update()
                    )
                    futures = [
                        executor.submit(
                            client.post,
                            f"/api/v1/onboarding/{run_id}/claim",
                            headers={
                                "Origin": "http://testserver",
                                "X-CSRF-Token": account["csrf_token"],
                            },
                            json={"expected_revision": state["revision"]},
                        )
                        for client, account in zip(clients, accounts, strict=True)
                    ]
                    try:
                        ready.wait()
                        pids = [backend_pids.get(timeout=10) for _ in range(2)]
                        assert len(set(pids + [blocker_pid])) == 3
                        deadline = monotonic() + 5
                        with test_engine.connect().execution_options(
                            isolation_level="AUTOCOMMIT"
                        ) as observer:
                            while True:
                                blockers = {
                                    pid: observer.scalar(
                                        text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                                    )
                                    for pid in pids
                                }
                                # One worker waits on the externally held run;
                                # the other waits on that worker's guest session.
                                winners = [pid for pid in pids if blocker_pid in blockers[pid]]
                                if len(winners) == 1:
                                    winner_pid = winners[0]
                                    loser_pid = next(pid for pid in pids if pid != winner_pid)
                                    if winner_pid in blockers[loser_pid]:
                                        break
                                for future in futures:
                                    if future.done():
                                        future.result()
                                assert monotonic() < deadline, (
                                    "Claims did not form the PostgreSQL lock chain"
                                )
                    finally:
                        blocker.rollback()
                assert loser_paused.wait(10), "Second claim never acquired the guest lock"
                finished, _ = wait(futures, timeout=20, return_when=FIRST_COMPLETED)
                assert finished, "Winner did not return after commit"
                winner = next(index for index, future in enumerate(futures) if future in finished)
                success = futures[winner].result(timeout=20)
                assert success.status_code == 200, success.text
                after_winner = _snapshot(test_engine)
                release_loser.set()
                responses = [future.result(timeout=20) for future in futures]
        finally:
            release_loser.set()
            ready.abort()
            claim_client.app.dependency_overrides.pop(get_db)

        assert sorted(response.status_code for response in responses) == [200, 404]
        loser = 1 - winner
        rejected = responses[loser]
        assert rejected.json() == {
            "code": "onboarding_not_found",
            "message": "Onboarding resource was not found",
            "request_id": rejected.headers["x-request-id"],
        }
        assert "set-cookie" not in rejected.headers
        assert all(response.headers["cache-control"] == "no-store" for response in responses)
        assert success.json() == {
            **state,
            "revision": state["revision"] + 1,
            "saved_to_account": True,
        }
        assert _snapshot(test_engine) == after_winner

        owner_id = UUID(accounts[winner]["user_id"])
        saved_run = next(row for row in after_winner[2] if row["id"] == run_id)
        claimed_at = saved_run["claimed_at"]
        assert claimed_at is not None
        expected = deepcopy(before)
        for row in expected[0]:
            if row["id"] == owner_id:
                row["current_run_id"] = run_id
        for row in expected[1]:
            if row["id"] == guest_id:
                row["revoked_at"] = claimed_at
        for row in expected[2]:
            if row["id"] == run_id:
                row.update(user_id=owner_id, claimed_at=claimed_at, revision=state["revision"] + 1)
        assert after_winner == expected
        for index, client in enumerate(clients):
            old_id = accounts[index]["current_run_id"]
            assert client.get(f"/api/v1/onboarding/{old_id}").json() == old_states[index]
            context = client.get("/api/v1/context").json()
            assert context["account"]["current_run_id"] == (
                state["id"] if index == winner else old_id
            )
            assert set(context["saved_run_ids"]) == (
                {old_id, state["id"]} if index == winner else {old_id}
            )
