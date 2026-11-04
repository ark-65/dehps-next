ALTER TABLE qwen_selection_state ADD COLUMN last_scheduled_at timestamptz;
ALTER TABLE qwen_selection_state ADD COLUMN last_scheduled_feedback_seq bigint NOT NULL DEFAULT 0;
