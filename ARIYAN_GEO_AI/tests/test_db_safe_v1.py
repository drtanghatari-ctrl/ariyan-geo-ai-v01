"""db-safe-v1 tests: grand_project.db must never be silently re-created
over real data, and a daily automatic backup must be taken.

Reproduces the 16 Oct 2026 loss: the real database vanished from
offline_data and the app quietly created a fresh empty one."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "src", "main", "python"))

import grand_project_db as db  # noqa: E402
import grand_project_sync as sync  # noqa: E402


def _fill(root, rows=4000):
    """Make the real database comfortably larger than 1 MB."""
    conn = db.get_connection(root)
    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS filler (id INTEGER PRIMARY KEY, blob TEXT)")
        conn.executemany("INSERT INTO filler (blob) VALUES (?)",
                         [("x" * 400,) for _ in range(rows)])
    conn.close()


class DbSafeV1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        db._daily_done.clear()

    def tearDown(self):
        db._daily_done.clear()
        self.tmp.cleanup()

    def _path(self):
        return os.path.join(self.root, db.DB_FILENAME)

    def _new_day(self):
        db._daily_done.clear()

    # --- genuine first run ----------------------------------------------
    def test_first_run_creates_database_and_guard(self):
        pid = sync.get_or_create_default_grand_project(self.root)
        self.assertTrue(pid)
        self.assertTrue(os.path.getsize(self._path()) > 0)
        self.assertTrue(os.path.exists(os.path.join(self.root, db.GUARD_FILENAME)))

    # --- the 16 Oct scenario --------------------------------------------
    def test_missing_db_with_job_status_files_refuses_to_create(self):
        sync.get_or_create_default_grand_project(self.root)
        with open(os.path.join(self.root, "wide_area_search_status_d27dec.json"), "w") as fh:
            fh.write("{}")
        os.remove(self._path())
        self._new_day()
        with self.assertRaises(db.DatabaseMissingError):
            sync.get_or_create_default_grand_project(self.root)
        self.assertFalse(os.path.exists(self._path()),
                         "must not leave a fresh empty database behind")

    def test_missing_db_with_only_status_files_no_guard(self):
        # status files alone (guard also lost) are still enough evidence
        with open(os.path.join(self.root, "wide_area_search_status_abc123.json"), "w") as fh:
            fh.write("{}")
        with self.assertRaises(db.DatabaseMissingError):
            db.get_connection(self.root)

    def test_missing_db_message_lists_backup(self):
        backup = os.path.join(self.root, "grand_project_backup_20260922.db")
        sqlite3.connect(backup).execute("CREATE TABLE t (x)").connection.close()
        with self.assertRaises(db.DatabaseMissingError) as cm:
            db.get_connection(self.root)
        self.assertIn("grand_project_backup_20260922.db", str(cm.exception))

    def test_zero_byte_db_treated_as_missing(self):
        sync.get_or_create_default_grand_project(self.root)
        open(self._path(), "w").close()  # truncate to 0 bytes
        self._new_day()
        with self.assertRaises(db.DatabaseMissingError):
            db.get_connection(self.root)

    def test_override_file_allows_new_database_once(self):
        sync.get_or_create_default_grand_project(self.root)
        os.remove(self._path())
        flag = os.path.join(self.root, db.ALLOW_NEW_FILENAME)
        open(flag, "w").close()
        self._new_day()
        self.assertTrue(sync.get_or_create_default_grand_project(self.root))
        self.assertFalse(os.path.exists(flag), "override must be one-shot")

    # --- swapped-for-empty detection --------------------------------------
    def test_much_smaller_replacement_is_refused(self):
        _fill(self.root)
        big = os.path.getsize(self._path())
        self.assertGreater(big, db._SHRINK_MIN_PREVIOUS_BYTES)
        self._new_day()
        db.get_connection(self.root).close()  # guard records the big size
        os.remove(self._path())
        sqlite3.connect(self._path()).execute("CREATE TABLE t (x)").connection.close()
        self._new_day()
        with self.assertRaises(db.DatabaseSuspectError):
            db.get_connection(self.root)

    def test_deleting_rows_does_not_trigger_shrink_guard(self):
        _fill(self.root)
        self._new_day()
        db.get_connection(self.root).close()
        conn = db.get_connection(self.root)
        with conn:
            conn.execute("DELETE FROM filler")
        conn.close()
        self._new_day()
        db.get_connection(self.root).close()  # no exception

    # --- automatic backup ------------------------------------------------
    def test_daily_backup_is_a_valid_copy(self):
        _fill(self.root, rows=50)
        self._new_day()
        db.get_connection(self.root).close()
        folder = os.path.join(self.root, db.BACKUP_DIRNAME)
        autos = [n for n in os.listdir(folder) if n.startswith(db.AUTO_BACKUP_PREFIX)]
        self.assertEqual(len(autos), 1)
        c = sqlite3.connect(os.path.join(folder, autos[0]))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM filler").fetchone()[0], 50)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        c.close()

    def test_backup_taken_once_per_day(self):
        _fill(self.root, rows=10)
        for _ in range(5):
            db.get_connection(self.root).close()
        folder = os.path.join(self.root, db.BACKUP_DIRNAME)
        self.assertLessEqual(len(os.listdir(folder)), 1)

    def test_prune_keeps_newest_and_largest(self):
        folder = os.path.join(self.root, db.BACKUP_DIRNAME)
        os.makedirs(folder)
        for day in range(1, 16):
            with open(os.path.join(folder, "%s202609%02d.db" % (db.AUTO_BACKUP_PREFIX, day)), "w") as fh:
                fh.write("x" * (5000 if day == 1 else 10))
        db._prune_auto_backups(folder)
        left = sorted(os.listdir(folder))
        self.assertIn(db.AUTO_BACKUP_PREFIX + "20260901.db", left)  # largest kept
        self.assertIn(db.AUTO_BACKUP_PREFIX + "20260915.db", left)  # newest kept
        self.assertEqual(len(left), db.AUTO_BACKUP_KEEP + 1)

    def test_backup_failure_never_blocks_open(self):
        _fill(self.root, rows=5)
        # put a FILE where the backup folder should be
        os.rename(os.path.join(self.root, db.BACKUP_DIRNAME),
                  os.path.join(self.root, "moved_backups"))
        open(os.path.join(self.root, db.BACKUP_DIRNAME), "w").close()
        self._new_day()
        db.get_connection(self.root).close()  # no exception

    def test_backups_folder_counts_as_evidence(self):
        _fill(self.root, rows=5)
        self._new_day()
        db.get_connection(self.root).close()
        os.remove(self._path())
        os.remove(os.path.join(self.root, db.GUARD_FILENAME))
        self._new_day()
        with self.assertRaises(db.DatabaseMissingError):
            db.get_connection(self.root)


if __name__ == "__main__":
    unittest.main()
