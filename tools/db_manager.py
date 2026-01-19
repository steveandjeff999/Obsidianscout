#!/usr/bin/env python3
"""
Simple DB manager UI using Tkinter.

Features:
- Open a local SQLite file or enter a SQLAlchemy URI
- List tables, view schema, browse rows (LIMIT 1000)
- Run arbitrary SQL
- Basic edit/delete for rows when table has a single primary key

Usage: python tools/db_manager.py
"""
import sqlite3
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    from sqlalchemy import create_engine, inspect, text
    HAS_SQLALCHEMY = True
except Exception:
    HAS_SQLALCHEMY = False


class DBManagerApp:
    def __init__(self, root):
        self.root = root
        root.title('DB Manager')

        frm = ttk.Frame(root, padding=8)
        frm.grid(sticky='nsew')
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        # Connection row
        conn_frame = ttk.Frame(frm)
        conn_frame.grid(sticky='ew')
        conn_frame.columnconfigure(1, weight=1)

        ttk.Label(conn_frame, text='DB file or SQLAlchemy URI:').grid(row=0, column=0)
        self.conn_entry = ttk.Entry(conn_frame)
        self.conn_entry.grid(row=0, column=1, sticky='ew', padx=4)
        ttk.Button(conn_frame, text='Browse SQLite', command=self.browse_sqlite).grid(row=0, column=2)
        ttk.Button(conn_frame, text='Connect', command=self.connect).grid(row=0, column=3, padx=4)

        # Left: tables
        left = ttk.Frame(frm)
        left.grid(row=1, column=0, sticky='nsw', pady=8)
        ttk.Label(left, text='Tables').pack(anchor='w')
        self.tables_lb = tk.Listbox(left, height=20)
        self.tables_lb.pack(fill='y')
        self.tables_lb.bind('<<ListboxSelect>>', lambda e: self.on_table_select())

        # Right: details
        right = ttk.Frame(frm)
        right.grid(row=1, column=1, sticky='nsew', padx=8)
        frm.columnconfigure(1, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        btns = ttk.Frame(right)
        btns.grid(row=0, column=0, sticky='ew')
        ttk.Button(btns, text='Refresh Tables', command=self.list_tables).pack(side='left')
        ttk.Button(btns, text='Show Schema', command=self.show_schema).pack(side='left', padx=4)
        ttk.Button(btns, text='Run SQL', command=self.run_sql_dialog).pack(side='left')

        # Treeview for rows
        self.tree = ttk.Treeview(right, columns=(), show='headings')
        self.tree.grid(row=1, column=0, sticky='nsew')
        self.tree.bind('<Double-1>', self.on_cell_double_click)

        vsb = ttk.Scrollbar(right, orient='vertical', command=self.tree.yview)
        vsb.grid(row=1, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=vsb.set)

        bottom = ttk.Frame(right)
        bottom.grid(row=2, column=0, sticky='ew', pady=6)
        ttk.Button(bottom, text='Refresh Rows', command=self.load_table_rows).pack(side='left')
        ttk.Button(bottom, text='Add Row', command=self.add_row_dialog).pack(side='left', padx=4)
        ttk.Button(bottom, text='Delete Row', command=self.delete_selected_row).pack(side='left')

        self.conn = None
        self.engine = None
        self.inspector = None
        self.current_table = None
        self.current_columns = []
        self.pk_columns = []

    def browse_sqlite(self):
        p = filedialog.askopenfilename(filetypes=[('SQLite DB', '*.db;*.sqlite;*.sqlite3'), ('All files', '*.*')])
        if p:
            self.conn_entry.delete(0, tk.END)
            self.conn_entry.insert(0, p)

    def connect(self):
        uri = self.conn_entry.get().strip()
        if not uri:
            messagebox.showinfo('Info', 'Enter a path to a SQLite file or a SQLAlchemy URI')
            return

        # Close previous
        try:
            if self.conn:
                try:
                    self.conn.close()
                except Exception:
                    pass
            if self.engine:
                try:
                    self.engine.dispose()
                except Exception:
                    pass
        except Exception:
            pass

        # If it's a file path, use sqlite3
        if Path(uri).exists() or uri.endswith('.db') or uri.endswith('.sqlite'):
            try:
                self.conn = sqlite3.connect(uri)
                self.engine = None
                self.inspector = None
            except Exception as e:
                messagebox.showerror('Error', f'Failed to open SQLite DB:\n{e}')
                return
        else:
            if not HAS_SQLALCHEMY:
                messagebox.showerror('Error', 'SQLAlchemy is not installed; only SQLite files are supported')
                return
            try:
                self.engine = create_engine(uri)
                self.inspector = inspect(self.engine)
                # create a lightweight connection for simple execute
                self.conn = None
            except Exception as e:
                messagebox.showerror('Error', f'Failed to create engine:\n{e}')
                return

        self.list_tables()

    def list_tables(self):
        self.tables_lb.delete(0, tk.END)
        try:
            tables = []
            if self.engine and self.inspector:
                tables = self.inspector.get_table_names()
            elif self.conn:
                cur = self.conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                self.tables_lb.insert(tk.END, t)
        except Exception as e:
            messagebox.showerror('Error listing tables', str(e))

    def on_table_select(self):
        sel = self.tables_lb.curselection()
        if not sel:
            return
        table = self.tables_lb.get(sel[0])
        self.current_table = table
        self.show_schema()
        self.load_table_rows()

    def show_schema(self):
        if not self.current_table:
            sel = self.tables_lb.curselection()
            if not sel:
                messagebox.showinfo('Info', 'Select a table first')
                return
            self.current_table = self.tables_lb.get(sel[0])

        try:
            if self.engine and self.inspector:
                cols = self.inspector.get_columns(self.current_table)
                pk = self.inspector.get_pk_constraint(self.current_table).get('constrained_columns', [])
                schema = '\n'.join([f"{c['name']} ({c.get('type')})" for c in cols])
                self.pk_columns = pk or []
            elif self.conn:
                cur = self.conn.cursor()
                cur.execute(f"PRAGMA table_info('{self.current_table}')")
                info = cur.fetchall()
                schema_lines = []
                pk_cols = []
                for cid, name, typ, notnull, dflt, pk in info:
                    schema_lines.append(f"{name} ({typ}) pk={pk}")
                    if pk:
                        pk_cols.append(name)
                schema = '\n'.join(schema_lines)
                self.pk_columns = pk_cols
            else:
                schema = 'No connection'

            messagebox.showinfo(f'Schema: {self.current_table}', schema)
        except Exception as e:
            messagebox.showerror('Error getting schema', str(e))

    def load_table_rows(self):
        if not self.current_table:
            messagebox.showinfo('Info', 'Select a table first')
            return

        def work():
            try:
                if self.engine and self.inspector:
                    with self.engine.connect() as conn:
                        rs = conn.execute(text(f"SELECT * FROM {self.current_table} LIMIT 1000"))
                        rows = rs.fetchall()
                        cols = rs.keys()
                elif self.conn:
                    cur = self.conn.cursor()
                    cur.execute(f"SELECT * FROM '{self.current_table}' LIMIT 1000")
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                else:
                    raise RuntimeError('No DB connection')

                self.current_columns = list(cols)

                # update UI in main thread
                def update_ui():
                    self.tree.delete(*self.tree.get_children())
                    self.tree.config(columns=self.current_columns)
                    for c in self.current_columns:
                        self.tree.heading(c, text=c)
                        self.tree.column(c, width=120)
                    for r in rows:
                        # convert row to strings
                        self.tree.insert('', tk.END, values=[str(x) if x is not None else '' for x in r])

                self.root.after(0, update_ui)
            except Exception:
                tb = traceback.format_exc()
                self.root.after(0, lambda: messagebox.showerror('Error loading rows', tb))

        threading.Thread(target=work, daemon=True).start()

    def run_sql_dialog(self):
        txt = simpledialog.askstring('Run SQL', 'Enter SQL to run (SELECT only recommended)')
        if not txt:
            return

        def work():
            try:
                if self.engine:
                    with self.engine.connect() as conn:
                        rs = conn.execute(text(txt))
                        try:
                            rows = rs.fetchall()
                            cols = rs.keys()
                        except Exception:
                            rows = []
                            cols = []
                elif self.conn:
                    cur = self.conn.cursor()
                    cur.execute(txt)
                    try:
                        rows = cur.fetchall()
                        cols = [d[0] for d in cur.description]
                        self.conn.commit()
                    except Exception:
                        rows = []
                        cols = []
                else:
                    raise RuntimeError('No DB connection')

                self.current_columns = list(cols)

                def update_ui():
                    self.tree.delete(*self.tree.get_children())
                    if cols:
                        self.tree.config(columns=cols)
                        for c in cols:
                            self.tree.heading(c, text=c)
                            self.tree.column(c, width=120)
                        for r in rows:
                            self.tree.insert('', tk.END, values=[str(x) if x is not None else '' for x in r])
                    else:
                        messagebox.showinfo('SQL executed', 'SQL executed (no results to display)')

                self.root.after(0, update_ui)
            except Exception:
                tb = traceback.format_exc()
                self.root.after(0, lambda: messagebox.showerror('Error running SQL', tb))

        threading.Thread(target=work, daemon=True).start()

    def on_cell_double_click(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not col:
            return
        col_index = int(col.replace('#', '')) - 1
        cur_vals = self.tree.item(item, 'values')
        old = cur_vals[col_index]

        if not self.pk_columns:
            messagebox.showinfo('Editing not allowed', 'Table has no primary key; editing is not supported')
            return

        new = simpledialog.askstring('Edit cell', f'Old value: {old}\nNew value:')
        if new is None:
            return

        # Build update using pk
        pk_vals = {}
        for pk in self.pk_columns:
            try:
                idx = self.current_columns.index(pk)
                pk_vals[pk] = cur_vals[idx]
            except ValueError:
                messagebox.showerror('Error', 'Primary key column not found in current result set')
                return

        col_name = self.current_columns[col_index]

        placeholders = ' AND '.join([f"{k} = :{k}" for k in pk_vals.keys()])
        params = {k: v for k, v in pk_vals.items()}
        params['__new'] = new

        sql = f"UPDATE {self.current_table} SET {col_name} = :__new WHERE {placeholders}"

        try:
            if self.engine:
                with self.engine.connect() as conn:
                    conn.execute(text(sql), params)
            elif self.conn:
                cur = self.conn.cursor()
                cur.execute(sql.replace(':__new', '?').replace(':' , ''), tuple([params['__new']] + list(pk_vals.values())))
                self.conn.commit()
            else:
                raise RuntimeError('No DB connection')
            messagebox.showinfo('Updated', 'Row updated')
            self.load_table_rows()
        except Exception as e:
            messagebox.showerror('Update failed', str(e))

    def add_row_dialog(self):
        if not self.current_table:
            messagebox.showinfo('Info', 'Select a table first')
            return
        # Ask for comma-separated column=value pairs
        val = simpledialog.askstring('Add row', 'Enter new row as comma-separated column=value pairs\nExample: col1=val1,col2=val2')
        if not val:
            return
        try:
            pairs = [p.strip() for p in val.split(',') if p.strip()]
            data = {}
            cols = []
            vals = []
            for p in pairs:
                if '=' not in p:
                    raise ValueError('Bad pair: ' + p)
                k, v = p.split('=', 1)
                cols.append(k.strip())
                vals.append(v.strip())

            sql = f"INSERT INTO {self.current_table} ({', '.join(cols)}) VALUES ({', '.join([':v'+str(i) for i in range(len(vals))])})"
            params = {'v'+str(i): vals[i] for i in range(len(vals))}

            if self.engine:
                with self.engine.connect() as conn:
                    conn.execute(text(sql), params)
            elif self.conn:
                cur = self.conn.cursor()
                qmarks = ','.join(['?']*len(vals))
                cur.execute(f"INSERT INTO {self.current_table} ({', '.join(cols)}) VALUES ({qmarks})", vals)
                self.conn.commit()
            messagebox.showinfo('Inserted', 'Row inserted')
            self.load_table_rows()
        except Exception as e:
            messagebox.showerror('Insert failed', str(e))

    def delete_selected_row(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo('Info', 'Select a row to delete')
            return
        if not self.pk_columns:
            messagebox.showinfo('Not supported', 'Table has no primary key; delete not supported')
            return
        if not messagebox.askyesno('Confirm', 'Delete selected row?'):
            return

        item = sel[0]
        vals = self.tree.item(item, 'values')
        pk_vals = {}
        for pk in self.pk_columns:
            try:
                idx = self.current_columns.index(pk)
                pk_vals[pk] = vals[idx]
            except ValueError:
                messagebox.showerror('Error', 'Primary key column not found in current result set')
                return

        where = ' AND '.join([f"{k} = :{k}" for k in pk_vals.keys()])
        params = pk_vals
        sql = f"DELETE FROM {self.current_table} WHERE {where}"
        try:
            if self.engine:
                with self.engine.connect() as conn:
                    conn.execute(text(sql), params)
            elif self.conn:
                cur = self.conn.cursor()
                # sqlite3 parameter style is ? not :name when passing tuple
                cur.execute(sql.replace(':', ''), tuple(pk_vals.values()))
                self.conn.commit()
            messagebox.showinfo('Deleted', 'Row deleted')
            self.load_table_rows()
        except Exception as e:
            messagebox.showerror('Delete failed', str(e))


def main():
    root = tk.Tk()
    app = DBManagerApp(root)
    root.geometry('1000x600')
    root.mainloop()


if __name__ == '__main__':
    main()
