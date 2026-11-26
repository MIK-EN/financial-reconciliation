import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/manrope";

import { App } from "./App";
import { Trainer } from "./trainer/Trainer";
import "./styles.css";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Root element is missing");
}

createRoot(root).render(
  <StrictMode>
    {window.location.pathname === "/trainer" ? <Trainer /> : <App />}
  </StrictMode>,
);
