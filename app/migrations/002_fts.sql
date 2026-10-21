-- Global search across item titles, note bodies, and file names.
-- One FTS5 virtual table with a `kind` column, triggers keep it in sync.
CREATE VIRTUAL TABLE search_index USING fts5(
  kind UNINDEXED,          -- 'item' | 'note' | 'file'
  ref_id UNINDEXED,        -- rowid in the source table
  title,
  body,
  tokenize = "unicode61 remove_diacritics 2"
);

-- items -> search_index
CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('item', new.id, new.title, new.tags);
END;
CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN
  DELETE FROM search_index WHERE kind='item' AND ref_id=new.id;
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('item', new.id, new.title, new.tags);
END;
CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN
  DELETE FROM search_index WHERE kind='item' AND ref_id=old.id;
END;

-- notes -> search_index
CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('note', new.id, '', new.body_md);
END;
CREATE TRIGGER notes_au AFTER UPDATE ON notes BEGIN
  DELETE FROM search_index WHERE kind='note' AND ref_id=new.id;
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('note', new.id, '', new.body_md);
END;
CREATE TRIGGER notes_ad AFTER DELETE ON notes BEGIN
  DELETE FROM search_index WHERE kind='note' AND ref_id=old.id;
END;

-- files -> search_index
CREATE TRIGGER files_ai AFTER INSERT ON files BEGIN
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('file', new.id, new.original_name, new.tags);
END;
CREATE TRIGGER files_au AFTER UPDATE ON files BEGIN
  DELETE FROM search_index WHERE kind='file' AND ref_id=new.id;
  INSERT INTO search_index(kind, ref_id, title, body)
  VALUES ('file', new.id, new.original_name, new.tags);
END;
CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
  DELETE FROM search_index WHERE kind='file' AND ref_id=old.id;
END;
