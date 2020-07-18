#!/usr/bin/env python
# -*- coding: utf-8 -*-

from sql2graph.schema2 import generate_iter_query
from sql2graph.schema2 import SchemaHelper, Schema, Column, ForeignColumn, \
    Property, IntegerProperty, Relation, Entity, Reference
from sql2graph.schema2 import indent, generate_union_query


class SQL2GraphExporter(object):

    # to change the TSV header line
    nodes_header_override = None
    rels_header_override = None  # not used currently
    output_encoding = 'UTF8'

    def __init__(self, schema, entities, strict=True):
        self.cfg = None
        self.db = None
        self.strict = strict

        self.schema = SchemaHelper(schema, entities, strict=self.strict)
        self.entity_limit = None
        self.nodes_filename = None
        self.relations_filename = None

        self.all_properties = self.schema.fetch_all_fields(self.cfg, self.db)
        self.all_relations_properties = self.schema.fetch_all_relations_properties(
            self.cfg, self.db)

        self.check_nodes_header_override()

    def check_nodes_header_override(self):

        all_column_names = [cname for cname, ctype in self.all_properties
                            ] + ["kind"]
        for incols, outcols in list(self.nodes_header_override.items()):
            # simple column renaming
            if isinstance(incols, (str, )):
                if outcols is not None:
                    if incols not in all_column_names:
                        del self.nodes_header_override[incols]
            # merging columns
            elif isinstance(incols, (tuple, )):
                valid_columns = [c for c in incols if c in all_column_names]
                self.nodes_header_override[tuple(
                    valid_columns)] = self.nodes_header_override.pop(incols)

    def set_nodes_filename(self, filename):
        self.nodes_filename = filename

    def set_rels_filename(self, filename):
        self.relations_filename = filename

    def set_entity_export_limit(self, limit):
        if limit:
            self.entity_limit = limit

    @classmethod
    def generate_tsvfile_output_query(cls,
                                      query,
                                      output_filename,
                                      modify_headers={}):

        if modify_headers:
            select_lines = []

            for incols, outcols in modify_headers.items():
                # simple column renaming
                if isinstance(incols, (str, )):
                    if outcols is not None:
                        select_lines.append("wrapped.%s AS %s" %
                                            (incols, outcols))
                # merging columns
                elif isinstance(incols, (tuple, )):
                    infunc, outname = outcols
                    k = infunc(*["wrapped.%s::text" % c for c in incols])
                    select_lines.append("%s AS %s" % (k, outname))

            select_lines = ",\n".join(select_lines)

            query = """
SELECT
%(fields)s
FROM (
%(query)s
)
AS wrapped
        """ % dict(query=indent(query, '   '),
                   fields=indent(select_lines, '   '))

        return """
COPY(
%(query)s
)
TO '%(filename)s' CSV HEADER
DELIMITER E'\\t'
ENCODING '%(encoding)s';
""" % dict(query=indent(query, '   '),
           filename=output_filename,
           encoding=cls.output_encoding)

    # --- create temporary mapping table
    def create_mapping_table_query(self, multiple=False):
        print("""
-- Create the mapping table
-- between (entity, pk) tuples and incrementing node IDs
""")
        node_queries = []
        for columns, joins in self.schema.fetch_all(
                self.cfg, self.db,
            [(n, t) for n, t in self.all_properties if n in ('kind', 'pk')]):
            if columns and joins:
                node_queries.append(
                    generate_iter_query(columns,
                                        joins,
                                        limit=self.entity_limit,
                                        order_by='pk'))

        if multiple:

            query = """
CREATE TEMPORARY TABLE entity_mapping
(
    node_id             SERIAL,
    entity              TEXT,
    pk                  BIGINT
);
"""

            insert_entity_query = """
INSERT INTO entity_mapping
    (entity, pk)
%s
ORDER BY pk;\n"""
            for q in node_queries:
                query += insert_entity_query % indent(q, '    ')

            query += """-- create index to speedup lookups
CREATE INDEX ON entity_mapping (entity, pk);

ANALYZE entity_mapping;
"""
            return query

        else:

            mapping_query = """
SELECT
    kind AS entity,
    pk,
    row_number() OVER (ORDER BY kind, pk) as node_id
FROM
(
%s
)
AS entity_union \n""" % indent(generate_union_query(node_queries), '    ')

            temp_mapping_table = """
DROP TABLE IF EXISTS entity_mapping;

CREATE TEMPORARY TABLE entity_mapping AS
(
%s
);

-- create index to speedup lookups
CREATE INDEX ON entity_mapping (entity, pk);

ANALYZE entity_mapping;

""" % indent(mapping_query, '    ')

            return temp_mapping_table

    # --- save the full nodes tables to file
    def create_nodes_query(self, multiple=False):

        node_queries = []
        for columns, joins in self.schema.fetch_all(
                self.cfg, self.db,
                self.all_properties if not multiple else []):
            if columns and joins:
                node_queries.append(
                    generate_iter_query(columns,
                                        joins,
                                        limit=self.entity_limit,
                                        order_by='pk'))

        #node_queries = ["""\n%s\nORDER BY pk\n""" % q for q in node_queries]
        headers = None

        if self.nodes_header_override:
            # start with 1-to-1 name map
            headers = dict([(name, name)
                            for (name, maptype) in self.all_properties])

            # fix some headers
            headers.update(self.nodes_header_override)

        if multiple:
            qs = []
            for i, q in enumerate(node_queries, start=1):
                qs.append(
                    self.generate_tsvfile_output_query(
                        """\n%s\nORDER BY pk\n""" % q,
                        self.nodes_filename.replace('.csv', '.%04d.csv' % i),
                        headers))
            return "\n".join(qs)
        else:
            #ordered_union_query = """\n%s\nORDER BY kind, pk\n""" % generate_union_query(node_queries)
            ordered_union_query = """\n%s\nORDER BY kind, pk\n""" % generate_union_query(
                node_queries)

            return self.generate_tsvfile_output_query(ordered_union_query,
                                                      self.nodes_filename,
                                                      headers)

    def create_relationships_query(self, multiple=False):

        rels_queries = []

        if multiple:
            for relations in self.schema.fetch_all_relations(
                    self.cfg, self.db):
                if not relations:
                    continue
                for columns, joins in relations:
                    rels_queries.append(generate_iter_query(columns, joins))
            qs = []
            for i, q in enumerate(rels_queries, start=1):
                qs.append(
                    self.generate_tsvfile_output_query(
                        q,
                        self.relations_filename.replace(
                            '.csv', '.%04d.csv' % i)))
            return "\n".join(qs)
        else:
            for relations in self.schema.fetch_all_relations(
                    self.cfg, self.db, self.all_relations_properties):
                if not relations:
                    continue
                for columns, joins in relations:
                    rels_queries.append(generate_iter_query(columns, joins))
            return self.generate_tsvfile_output_query(
                generate_union_query(rels_queries), self.relations_filename)
