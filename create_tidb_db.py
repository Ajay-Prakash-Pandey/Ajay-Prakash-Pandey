#!/usr/bin/env python3
"""Create a TiDB/MySQL database and web user using PyMySQL (works on Windows without mysql client).

Usage example:
  python create_tidb_db.py \
    --host gateway01.ap-southeast-1.prod.alicloud.tidbcloud.com \
    --port 4000 \
    --admin-user 38qUjHYHj9Qmp27.root \
    --admin-pass ADMIN_PASSWORD \
    --ca-path C:\\path\\to\\ca.pem \
    --db portfolio_db \
    --web-user webuser \
    --web-pass MyWebPwd

If --web-pass is omitted, a secure password will be generated and printed.
If you prefer to pass CA as base64, use --ca-base64 instead of --ca-path.
"""

import argparse
import base64
import os
import re
import secrets
import sys
import tempfile
from urllib.parse import quote

try:
    import pymysql
except Exception as e:
    print('PyMySQL is required. Install with: pip install PyMySQL')
    raise


def write_ca_from_base64(b64: str) -> str:
    data = base64.b64decode(b64)
    fd, path = tempfile.mkstemp(prefix='tidb-ca-', suffix='.pem')
    os.close(fd)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', required=True)
    p.add_argument('--port', type=int, default=4000)
    p.add_argument('--admin-user', required=True)
    p.add_argument('--admin-pass', required=True)
    p.add_argument('--ca-path')
    p.add_argument('--ca-base64')
    p.add_argument('--db', default='portfolio_db')
    p.add_argument('--web-user', default='webuser')
    p.add_argument('--web-pass')
    args = p.parse_args()

    ca_path = None
    if args.ca_base64:
        ca_path = write_ca_from_base64(args.ca_base64)
        print('Wrote CA to', ca_path)
    elif args.ca_path:
        if not os.path.exists(args.ca_path):
            print('CA path not found:', args.ca_path)
            sys.exit(1)
        ca_path = args.ca_path

    web_pwd = args.web_pass or secrets.token_urlsafe(20)

    connect_kwargs = dict(host=args.host, port=args.port, user=args.admin_user, password=args.admin_pass, cursorclass=pymysql.cursors.DictCursor)
    if ca_path:
        connect_kwargs['ssl'] = {'ca': ca_path}

    print('Connecting to', args.host, 'port', args.port)
    try:
        conn = pymysql.connect(**connect_kwargs)
    except Exception as e:
        print('Connection failed:', e)
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            db_name = args.db
            web_user = args.web_user
            db_quoted = f"`{db_name.replace('`', '``')}`"
            user_quoted = conn.escape(web_user)
            password_quoted = conn.escape(web_pwd)

            cur.execute(f"CREATE DATABASE IF NOT EXISTS {db_quoted};")
            print('Created or verified database', db_name)
            cur.execute(
                f"CREATE USER IF NOT EXISTS {user_quoted}@'%' IDENTIFIED BY {password_quoted};"
            )
            cur.execute(
                f"GRANT ALL PRIVILEGES ON {db_quoted}.* TO {user_quoted}@'%';"
            )
            cur.execute('FLUSH PRIVILEGES;')
            conn.commit()
            print('Created/updated web user:', web_user)
            print('Web user password:', web_pwd)
            url_user = quote(web_user, safe='')
            url_pass = quote(web_pwd, safe='')
            db_url = f"mysql+pymysql://{url_user}:{url_pass}@{args.host}:{args.port}/{db_name}?charset=utf8mb4"
            print('\nDATABASE_URL=')
            print(db_url)
            if ca_path:
                with open(ca_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode('ascii')
                print('\nTIDB_CA_BASE64=')
                print(b64)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
