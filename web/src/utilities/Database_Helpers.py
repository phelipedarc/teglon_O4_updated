import os
import logging
import mysql.connector
from mysql.connector import Error
import MySQLdb as my
# import mysqlclient as my
from configparser import RawConfigParser
import time
import sys

# The per-query progress chatter ("Executing 1/1", "fetching results", ...) is the
# main source of stdout flooding; route it to DEBUG so it is hidden by default and
# shown with --verbose. Message text is unchanged.
logger = logging.getLogger("teglon")


def _dbg(*args, **kwargs):
    """print-compatible shim -> logging.debug (joins args with spaces like print)."""
    logger.debug(" ".join(str(a) for a in args))

# Resolve the Settings.ini path: honor TEGLON_SETTINGS if set, otherwise look for a
# `Settings.ini` next to the repo root (../../../ from this file) and fall back to CWD.
_default_settings = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "Settings.ini",
)
configFile = os.environ.get("TEGLON_SETTINGS", _default_settings)
config = RawConfigParser()
config.read([configFile, "Settings.ini"])


def _db_param(env_key, ini_key, default):
    """Connection params resolve from the environment first, then Settings.ini, then a
    Docker-friendly default. This lets the same code run inside the Docker network
    (DATABASE_HOST=gw_db) or from the host (DATABASE_HOST=127.0.0.1, DATABASE_PORT=53306)
    with no file edits and no port-forwarding/tunnel."""
    val = os.environ.get(env_key)
    if val:
        return val
    try:
        return config.get("database", ini_key)
    except Exception:
        return default


db_name = _db_param("DATABASE_NAME", "DATABASE_NAME", "teglon")
db_user = _db_param("DATABASE_USER", "DATABASE_USER", "teglon")
db_pwd = _db_param("DATABASE_PASSWORD", "DATABASE_PASSWORD", "4tegl0n123!!")
db_host = _db_param("DATABASE_HOST", "DATABASE_HOST", "gw_db")
db_port = int(_db_param("DATABASE_PORT", "DATABASE_PORT", "3306"))

def bulk_upload(query):
    success = False
    try:
        conn = mysql.connector.connect(user=db_user, password=db_pwd, host=db_host, port=db_port, database=db_name,
                                       allow_local_infile=True)
        cursor = conn.cursor()
        cursor.execute(query)
        conn.commit()
        success = True

    except Error as e:
        logger.error("Error in uploading CSV!")
        logger.error("%s" % e)
    except Exception as e:
        logger.error("Error in uploading CSV!")
        logger.error("%s" % e)
        test = 1
    finally:
        cursor.close()
        conn.close()

    return success

def query_db(query_list, commit=False, raise_on_error=False):

    results = []
    db = None
    cursor = None
    try:
        chunk_size = 1e+6
        db = my.connect(host=db_host, user=db_user, passwd=db_pwd, db=db_name, port=db_port)
        cursor = db.cursor()

        query_count = len(query_list)
        for qi, q in enumerate(query_list):
            current_q = qi + 1
            _dbg("Executing %s/%s" % (current_q, query_count))
            cursor.execute(q)

            if commit:  # used for updates, etc
                db.commit()

            streamed_results = []
            _dbg("\tfetching results...")
            while True:
                r = cursor.fetchmany(1000000)
                count = len(r)
                streamed_results += r
                size_in_mb = sys.getsizeof(streamed_results) / 1.0e+6

                _dbg("\t\tfetched: %s; current length: %s; running size: %0.3f MB" % (
                count, len(streamed_results), size_in_mb))

                if not r or count < chunk_size:
                    break

            results.append(streamed_results)

    # except Error as e:
    except Exception as e:
        logger.error("Exception: %s" % e)
        # Previously swallowed unconditionally, which let a failed statement
        # (e.g. a failed clobber/delete) proceed as if it had succeeded. Callers
        # that must abort on failure pass raise_on_error=True; the default keeps
        # the historical behavior for every other caller.
        if raise_on_error:
            raise
    finally:
        if cursor is not None:
            cursor.close()
        if db is not None:
            db.close()

    _dbg("Returning total results: %s" % len(results))
    return results

def batch_query(query_list):
    return_data = []
    batch_size = 500
    ii = 0
    jj = batch_size
    kk = len(query_list)

    _dbg("\nLength of data to query: %s" % kk)
    _dbg("Query batch size: %s" % batch_size)
    _dbg("Starting loop...")

    number_of_queries = len(query_list) // batch_size
    if len(query_list) % batch_size > 0:
        number_of_queries += 1

    query_num = 1
    payload = []
    while jj < kk:
        t1 = time.time()

        _dbg("%s:%s" % (ii, jj))
        payload = query_list[ii:jj]
        return_data += query_db(payload)

        ii = jj
        jj += batch_size
        t2 = time.time()

        _dbg("\n********* start DEBUG ***********")
        _dbg("Query %s/%s complete - execution time: %s" % (query_num, number_of_queries, (t2 - t1)))
        _dbg("********* end DEBUG ***********\n")

        query_num += 1

    _dbg("Out of loop...")

    t1 = time.time()

    _dbg("\n%s:%s" % (ii, kk))

    payload = query_list[ii:kk]
    return_data += query_db(payload)

    t2 = time.time()

    _dbg("\n********* start DEBUG ***********")
    _dbg("Query %s/%s complete - execution time: %s" % (query_num, number_of_queries, (t2 - t1)))
    _dbg("********* end DEBUG ***********\n")

    return return_data

def insert_records(query, data):
    _tstart = time.time()
    success = False
    try:
        conn = mysql.connector.connect(user=db_user, password=db_pwd, host=db_host, port=db_port, database=db_name,
                                       allow_local_infile=True)
        cursor = conn.cursor()
        cursor.executemany(query, data)

        conn.commit()
        success = True
    except Error as e:
        logger.error("Error: %s" % e)
    finally:
        cursor.close()
        conn.close()

    _tend = time.time()
    _dbg("\n********* start DEBUG ***********")
    _dbg("insert_records execution time: %s" % (_tend - _tstart))
    _dbg("********* end DEBUG ***********\n")
    return success

def batch_insert(insert_statement, insert_data, batch_size=50000):
    _tstart = time.time()

    i = 0
    j = batch_size
    k = len(insert_data)

    _dbg("\nLength of data to insert: %s" % len(insert_data))
    _dbg("Insert batch size: %s" % batch_size)
    _dbg("Starting loop...")

    number_of_inserts = len(insert_data) // batch_size
    if len(insert_data) % batch_size > 0:
        number_of_inserts += 1

    insert_num = 1
    payload = []
    while j < k:
        t1 = time.time()

        _dbg("%s:%s" % (i, j))
        payload = insert_data[i:j]

        if insert_records(insert_statement, payload):
            i = j
            j += batch_size
        else:
            raise ("Error inserting batch! Exiting...")

        t2 = time.time()

        _dbg("\n********* start DEBUG ***********")
        _dbg("INSERT %s/%s complete - execution time: %s" % (insert_num, number_of_inserts, (t2 - t1)))
        _dbg("********* end DEBUG ***********\n")

        insert_num += 1

    _dbg("Out of loop...")

    t1 = time.time()

    _dbg("\n%s:%s" % (i, k))

    payload = insert_data[i:k]
    if not insert_records(insert_statement, payload):
        raise ("Error inserting batch! Exiting...")

    t2 = time.time()

    _dbg("\n********* start DEBUG ***********")
    _dbg("INSERT %s/%s complete - execution time: %s" % (insert_num, number_of_inserts, (t2 - t1)))
    _dbg("********* end DEBUG ***********\n")

    _tend = time.time()

    _dbg("\n********* start DEBUG ***********")
    _dbg("batch_insert execution time: %s" % (_tend - _tstart))
    _dbg("********* end DEBUG ***********\n")

def delete_rows(delete_query, id_tuples_to_delete):
    # Start with
    batch_size = 10000
    i = 0
    j = batch_size
    k = len(id_tuples_to_delete)

    _dbg("\nLength of records to DELETE: %s" % k)
    _dbg("DELETE batch size: %s" % j)
    _dbg("Starting loop...")

    number_of_deletes = k // batch_size
    if k % batch_size > 0:
        number_of_deletes += 1

    delete_num = 1
    while j < k:
        t1 = time.time()
        _dbg("%s:%s" % (i, j))

        id_string = ",".join([str(id_tup[0]) for id_tup in id_tuples_to_delete[i:j]])
        query_db([delete_query % id_string], commit=True)
        i = j
        j += batch_size

        t2 = time.time()

        _dbg("\n********* start DEBUG ***********")
        _dbg("DELETE %s/%s complete - execution time: %s" % (delete_num, number_of_deletes, (t2 - t1)))
        _dbg("********* end DEBUG ***********\n")

        delete_num += 1

    t1 = time.time()
    _dbg("%s:%s" % (i, k))

    id_string = ",".join([str(id_tup[0]) for id_tup in id_tuples_to_delete[i:k]])
    query_db([delete_query % id_string], commit=True)

    t2 = time.time()

    _dbg("\n********* start DEBUG ***********")
    _dbg("DELETE %s/%s complete - execution time: %s" % (delete_num, number_of_deletes, (t2 - t1)))
    _dbg("********* end DEBUG ***********\n")
