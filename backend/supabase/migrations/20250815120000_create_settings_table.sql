-- Create the settings table
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY NOT NULL,
    value JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Enable Row Level Security
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;

-- Create a trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION set_updated_at_timestamp() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER handle_settings_updated_at
BEFORE UPDATE ON settings
FOR EACH ROW
EXECUTE FUNCTION set_updated_at_timestamp();

-- Policies for settings
-- Users should not be able to directly read/write all settings.
-- Access will be managed by specific API endpoints that can act as a gatekeeper.
-- For now, we will only allow the service_role to access this table.
CREATE POLICY "Allow service_role full access" ON settings
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Insert some default settings to bootstrap the system
-- We can store API keys, feature flags, etc., here.
-- Leaving it empty for now, to be populated by the new API.
INSERT INTO settings (key, value) VALUES
('llm.openai_api_key', 'null'),
('llm.anthropic_api_key', 'null'),
('feature.new_tool_system_enabled', 'true');
