-- Run once against an existing V1 database before starting the admin demo.
ALTER TABLE support_cases
ADD COLUMN IF NOT EXISTS resolution_source VARCHAR(20)
CHECK (resolution_source IN ('assistant', 'admin'));

ALTER TABLE support_cases
ADD COLUMN IF NOT EXISTS submission_key VARCHAR(128) UNIQUE;

-- Existing resolved cases predate assistant-saved answers.
UPDATE support_cases SET resolution_source = 'admin'
WHERE status = 'resolved' AND resolution_source IS NULL;
