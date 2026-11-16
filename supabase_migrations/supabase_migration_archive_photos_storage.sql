-- Архив фото: приватный бакет Storage для постоянного хранения снимков.
-- 16.11.2026. Независим от мультитенантной схемы (та ещё не применена).
-- Применяет владелец вручную в SQL Editor проекта guardian. Повторный запуск безопасен.
begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'archive-media',
    'archive-media',
    false,
    18 * 1024 * 1024,
    array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update set
    name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

-- Публичных политик нет: чтение и запись только сервисным ключом.

commit;

-- Проверка после применения:
--   select id, name, public, file_size_limit, allowed_mime_types
--     from storage.buckets where id = 'archive-media';
