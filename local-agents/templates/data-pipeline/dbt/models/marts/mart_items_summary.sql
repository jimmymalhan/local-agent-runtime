-- Mart: item status summary
with stg as (
    select * from {{ ref('stg_items') }}
)

select
    item_status,
    count(*) as item_count,
    min(processed_at) as first_processed,
    max(processed_at) as last_processed
from stg
group by 1
order by 2 desc
