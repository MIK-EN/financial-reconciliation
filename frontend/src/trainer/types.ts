export interface TrainerOption {
  id: string;
  text: string;
  explanation: string;
}

export interface Exercise {
  id: string;
  title: string;
  level: "A2" | "B1";
  situation: string;
  prompt: string;
  options: TrainerOption[];
  correct_option_id: string;
}

export interface Topic {
  id: string;
  title: string;
  description: string;
  exercises: Exercise[];
}

export interface TrainerData {
  content_hash: string;
  content: { schema_version: 1; version: string; topics: Topic[] };
}

export type Answers = Record<string, string>;
