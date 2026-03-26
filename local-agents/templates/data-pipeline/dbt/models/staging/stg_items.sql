-- Staging model: clean and rename raw items
with source as (
    select * from {{ source('raw', 'raw_data') }}
),

renamed as (
    select
        id::integer              as item_id,
        name::varchar            as item_name,
        status::varchar          as item_status,
        processed_at::timestamp  as processed_at,
        pipeline_version::varchar as pipeline_version
    from source
    where id is not null
)

select * from renamed
