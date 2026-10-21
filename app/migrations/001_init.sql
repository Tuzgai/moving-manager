-- One table for houses, tasks, and generic items. Type-specific and user-added
-- custom fields live in `fields` as JSON — we rarely query across them, and when
-- a field proves hot we can promote it to a real column without touching routes.
CREATE TABLE items (
  id          INTEGER PRIMARY KEY,
  type        TEXT    NOT NULL CHECK (type IN ('house','task','general')),
  title       TEXT    NOT NULL,
  status      TEXT    NOT NULL,
  tags        TEXT    NOT NULL DEFAULT '[]',    -- JSON array of strings
  fields      TEXT    NOT NULL DEFAULT '{}',    -- JSON object
  created_by  TEXT    NOT NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX items_type_status ON items(type, status);
CREATE INDEX items_updated     ON items(updated_at DESC);

-- Append-only notes log. One row per note; the UI never edits in place.
CREATE TABLE notes (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  author      TEXT    NOT NULL,
  body_md     TEXT    NOT NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX notes_item ON notes(item_id, created_at DESC);

-- Files live on disk; this is just the metadata row.
-- `stored_path` is relative to the configured files_root.
CREATE TABLE files (
  id             INTEGER PRIMARY KEY,
  original_name  TEXT NOT NULL,
  stored_path    TEXT NOT NULL UNIQUE,
  size_bytes     INTEGER NOT NULL,
  mime_type      TEXT NOT NULL,
  tags           TEXT NOT NULL DEFAULT '[]',
  uploaded_by    TEXT NOT NULL,
  uploaded_at    TEXT NOT NULL DEFAULT (datetime('now')),
  thumb_path     TEXT                                   -- NULL for non-images
);

CREATE TABLE item_files (
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  role    TEXT NOT NULL DEFAULT '',                     -- '', 'photo', 'offer_doc', 'quote_doc'
  PRIMARY KEY (item_id, file_id, role)
);

CREATE TABLE note_files (
  note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  PRIMARY KEY (note_id, file_id)
);

CREATE TABLE offers (
  id             INTEGER PRIMARY KEY,
  house_id       INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  amount_cents   INTEGER NOT NULL,
  sent_date      TEXT,
  expires_at     TEXT,
  status         TEXT NOT NULL,
  contingencies  TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX offers_house ON offers(house_id);

CREATE TABLE offer_files (
  offer_id INTEGER NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
  file_id  INTEGER NOT NULL REFERENCES files(id)  ON DELETE CASCADE,
  PRIMARY KEY (offer_id, file_id)
);

CREATE TABLE quotes (
  id             INTEGER PRIMARY KEY,
  task_id        INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  vendor         TEXT NOT NULL,
  amount_cents   INTEGER NOT NULL,
  received_date  TEXT,
  expires_at     TEXT,
  note           TEXT NOT NULL DEFAULT '',
  file_id        INTEGER REFERENCES files(id) ON DELETE SET NULL,
  chosen         INTEGER NOT NULL DEFAULT 0 CHECK (chosen IN (0,1)),
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Only one chosen quote per task. Partial unique index enforces it at the DB
-- level in addition to the repo logic that flips chosen in a transaction.
CREATE UNIQUE INDEX quotes_one_chosen ON quotes(task_id) WHERE chosen = 1;

CREATE TABLE contacts (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  role       TEXT,
  phone      TEXT,
  email      TEXT,
  notes      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE item_contacts (
  item_id    INTEGER NOT NULL REFERENCES items(id)    ON DELETE CASCADE,
  contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  PRIMARY KEY (item_id, contact_id)
);

CREATE TABLE key_dates (
  id         INTEGER PRIMARY KEY,
  title      TEXT NOT NULL,
  on_date    TEXT NOT NULL,
  category   TEXT NOT NULL CHECK (category IN ('buy','sell')),
  sub        TEXT NOT NULL DEFAULT '',
  item_id    INTEGER REFERENCES items(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX key_dates_on_date ON key_dates(on_date);

-- Activity feed. Each row is one event ("Stuart added a note to X").
CREATE TABLE activity (
  id         INTEGER PRIMARY KEY,
  actor      TEXT NOT NULL,
  verb       TEXT NOT NULL,      -- 'added-note', 'uploaded-file', 'rated', 'added-quote', ...
  text       TEXT NOT NULL,      -- rendered message, saved at event time
  item_id    INTEGER REFERENCES items(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX activity_recent ON activity(created_at DESC);
