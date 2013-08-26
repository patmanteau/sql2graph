-- COPY (SELECT * FROM l_url_url) TO stdout CSV HEADER DELIMITER E'\t';
COPY(
    SELECT
        link_ee.entity0 AS url1_fk,
        link_ee.entity1 AS url2_fk,
        link.begin_date_year,
        link.end_date_year,
        link_type.name,
        --link_type.long_link_phrase,
        --link_type.link_phrase,
        link_type.description
    FROM l_url_url link_ee
    JOIN link ON link_ee.link=link.id
    JOIN link_type ON link.link_type=link_type.id
)
TO stdout CSV HEADER DELIMITER E'\t';