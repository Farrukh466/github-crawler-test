-- Creates a schema to keep our data organized.
CREATE SCHEMA IF NOT EXISTS github_data;

-- Creates the table to store repository information.
-- This is part of the 'setup-postgres' step for the pipeline[cite: 18].
CREATE TABLE IF NOT EXISTS github_data.repositories (
    id VARCHAR(255) PRIMARY KEY, -- Using GitHub's unique ID prevents duplicates.
    name VARCHAR(255) NOT NULL,
    stargazer_count INT NOT NULL,
    crawled_at TIMESTAMPTZ DEFAULT NOW() -- Tracks when the row was last updated.
);