# SQL Query Compare

This project compares two SQL query scripts against the same database connection and tells you:

- what is different between the results
- which query is better when both results are equivalent
- how fast each query runs
- what error happened if a query fails

It also includes a browser UI where you can paste Query A and Query B, fill in the database connection, and click Compare.

## What it does

The script:

1. connects to your database using host, port, database, user, and password, or a full SQLAlchemy URL
2. executes `query_a.sql` and `query_b.sql`
3. measures execution time in milliseconds
4. compares returned columns and rows
5. prints a winner when both results are equivalent and one query is faster
6. shows database or driver errors, with optional traceback output in debug mode

## Requirements

- Python 3.10+
- Access to MariaDB, MySQL, PostgreSQL, or Oracle

Install dependencies:

```bash
pip install -r requirements.txt
```

Optional: create a `.env` file from `.env.example` and fill in your connection values. The script loads those values automatically.

## Usage

### Website

Start the web app:

```bash
python app.py
```

Then open `http://127.0.0.1:5000` and paste SQL A and SQL B into the form. If both queries run successfully, the page shows the comparison in HTML tables.

The default website values are already set for MariaDB:

- dialect: `mysql`
- driver: `pymysql`
- port: `3306`

Use these Dialect + Driver values in the form:

1. MySQL

- Dialect: `mysql`
- Driver: `pymysql`
- Port: `3306`

2. PostgreSQL

- Dialect: `postgresql`
- Driver: `psycopg`
- Port: `5432`

3. Oracle

- Dialect: `oracle`
- Driver: `oracledb`
- Port: usually `1521`

If you use Oracle, install the Oracle DB driver first:

```bash
pip install oracledb
```

### CLI

Example with explicit connection fields:

```bash
python compare_queries.py query_a.sql query_b.sql --dialect mysql --driver pymysql --host localhost --port 3306 --database mydb --user myuser --password mypass
```

Example with a full connection URL:

```bash
python compare_queries.py query_a.sql query_b.sql --url mysql+pymysql://myuser:mypass@localhost:3306/mydb
```

Enable debug traceback and JSON output:

```bash
python compare_queries.py query_a.sql query_b.sql --url mysql+pymysql://myuser:mypass@localhost:3306/mydb --debug --format json
```

## Notes

- This tool is best for read-only query comparison.
- The script opens a transaction and rolls it back after each query attempt to reduce accidental changes.
- If both queries return different rows, the tool will not declare a winner automatically.
- MariaDB works with the included `mysql+pymysql` configuration.
- Included drivers cover MariaDB, MySQL, and PostgreSQL. For other databases, install the matching SQLAlchemy driver and pass the correct dialect and optional driver.
- For Oracle service-name connections, URL examples can look like: `oracle+oracledb://user:password@host:1521/?service_name=ORCLPDB1`.
