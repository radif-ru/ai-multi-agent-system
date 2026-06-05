"""MAX-адаптер (мессенджер MAX, dev.max.ru/docs-api).

Тонкий транспортный слой поверх доменной модели: клиент Bot API, polling-цикл
и диспетчер апдейтов. Доменные слои (`core`/`agents`/`tools`/`memory`) не
меняются. См. спринт 09 и `_docs/architecture.md` §8.4.
"""
