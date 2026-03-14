# Жизненный цикл сервиса
service-started = <b>🚀 Сервис запущен</b>
    Мониторинг активен.

service-stopped = <b>🛑 Сервис остановлен</b>
    Мониторинг выключен.

# Изменения статуса нод
node-became-healthy = <b>✅ Нода онлайн</b>
    { $name } ({ $address }) доступна.

    📊 Ноды: { $online }/{ $total } онлайн, { $disabled } отключено

node-became-unhealthy = <b>❌ Нода офлайн</b>
    { $name } ({ $address }) недоступна.
    Причина: { $reason }

    📊 Ноды: { $online }/{ $total } онлайн, { $disabled } отключено

# Операции DNS
dns-record-added = <b>📝 DNS обновлён</b>
    Добавлен { $ip } → { $domain }

dns-record-removed = <b>🗑️ DNS удалён</b>
    Удалён { $ip } из { $domain }

# Ошибки
dns-operation-error = <b>⚠️ Ошибка DNS</b>
    Не удалось { $action } { $ip } для { $domain }
    Ошибка: { $error }

health-check-error = <b>⚠️ Ошибка проверки</b>
    Ошибка при проверке: { $error }

# Критические состояния
all-nodes-down = <b>🔴 КРИТИЧНО: Все ноды недоступны</b>
    Все { $total } нод недоступны.
    Затронуты: { $nodes }

    DNS записи очищены. Требуется немедленное вмешательство.

# Балансировка нагрузки
node-throttled = <b>⚡ Нода ограничена</b>
    { $name } ({ $address }) удалена из { $domain }
    Пользователей: { $users } (порог: { $threshold })

    DNS запись удалена для снижения нагрузки.

node-restored = <b>✅ Нода восстановлена</b>
    { $name } ({ $address }) добавлена в { $domain }
    Пользователей: { $users } (порог: { $threshold })

    DNS запись восстановлена, трафик принимается.

# Статус observer
observer-stale = <b>⚠️ Observer устарел</b>
    Скоуп: { $scope }
    Observer: { $observer }
    Детали: { $detail }

observer-recovered = <b>✅ Observer восстановлен</b>
    Скоуп: { $scope }
    Observer: { $observer }

observer-extended-stale = <b>🚨 Observer недоступен слишком долго</b>
    Скоуп: { $scope }
    Observer: { $observer }
    Детали: { $detail }

observer-mass-freeze = <b>🧊 Массовая деградация: freeze</b>
    Скоуп: { $scope }
    Observer: { $observer }
    Детали: { $detail }

observer-mass-freeze-cleared = <b>✅ Freeze снят</b>
    Скоуп: { $scope }
    Observer: { $observer }

# Решения observer
observer-drained = <b>🛑 Whitebox исключил ноду</b>
    { $name } ({ $address }) удалена из { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }

observer-restored = <b>✅ Whitebox восстановил ноду</b>
    { $name } ({ $address }) может вернуться в { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }

observer-blocked = <b>🟡 Исключение заблокировано</b>
    { $name } ({ $address }) осталась в { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }
    Детали: { $detail }

observer-shadow-drained = <b>🌓 Кандидат на исключение (shadow)</b>
    { $name } ({ $address }) была бы удалена из { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }

observer-shadow-restored = <b>🌓 Кандидат на возврат (shadow)</b>
    { $name } ({ $address }) вернулась бы в { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }

observer-force-active = <b>🧰 Override force-active</b>
    { $name } ({ $address }) оставлена активной для { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }

observer-force-drained = <b>🧰 Override force-drained</b>
    { $name } ({ $address }) принудительно удалена из { $domain }
    Скоуп: { $scope }
    Причины: { $reasons }
