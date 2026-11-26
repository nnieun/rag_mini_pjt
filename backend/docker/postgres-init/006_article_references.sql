BEGIN;

-- 같은 법 안의 조문 인용 관계. scripts/index_law.py가 인덱싱할 때 채운다.
-- 예: 제43조(과태료) -> 제36조(국내대리인 지정)
CREATE TABLE IF NOT EXISTS article_references (
    law_id varchar(20) NOT NULL,
    law_version varchar(20) NOT NULL,
    source_article varchar(20) NOT NULL,
    target_article varchar(20) NOT NULL,
    target_paragraph varchar(20) NOT NULL DEFAULT '',
    chunk_key varchar(200) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (law_id, law_version, source_article, target_article, target_paragraph, chunk_key)
);

CREATE INDEX IF NOT EXISTS ix_article_references_target ON article_references (law_id, law_version, target_article);

COMMIT;
