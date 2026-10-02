-- The applicants table and the exact privileges the application role receives.
-- Included by db_setup.sql once per database (\ir), connected as a superuser.
--
-- Why each grant exists (the app never needs anything beyond this list):
--   SELECT                            every analysis query, the /applicants endpoint, and the
--                                     "which ids do I already have" read before a pull.
--   INSERT                            Pull Data and load_data.py add new rows.
--   UPDATE (the two llm_* columns)    the upsert's ON CONFLICT ... DO UPDATE may only fill an
--                                     empty llm_generated_program / llm_generated_university.
--                                     No other column is updatable by this role.
--   USAGE on schema public            needed to reach the table; no CREATE on the schema.
-- Deliberately NOT granted: DELETE, TRUNCATE, REFERENCES, TRIGGER, DROP/ALTER (owner only).

SET ROLE gradcafe_m5_owner;

CREATE TABLE IF NOT EXISTS applicants (
    p_id                     INTEGER PRIMARY KEY,
    program                  TEXT,
    comments                 TEXT,
    date_added               DATE,
    url                      TEXT,
    status                   TEXT,
    term                     TEXT,
    us_or_international      TEXT,
    gpa                      FLOAT,
    gre                      FLOAT,
    gre_v                    FLOAT,
    gre_aw                   FLOAT,
    degree                   TEXT,
    llm_generated_program    TEXT,
    llm_generated_university TEXT
);

-- Start from nothing, then grant exactly what is listed above (re-running is harmless).
REVOKE ALL ON TABLE applicants FROM PUBLIC;
REVOKE ALL ON TABLE applicants FROM gradcafe_m5_app;
GRANT SELECT, INSERT ON TABLE applicants TO gradcafe_m5_app;
GRANT UPDATE (llm_generated_program, llm_generated_university)
    ON TABLE applicants TO gradcafe_m5_app;

RESET ROLE;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM gradcafe_m5_app;
GRANT USAGE ON SCHEMA public TO gradcafe_m5_app;
