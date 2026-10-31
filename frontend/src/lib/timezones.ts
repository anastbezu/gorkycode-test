// Справочник часовых поясов для настроек (product-06).

export interface TimezoneOption {
  iana: string;
  city: string;
  utcOffset: string; // "UTC+3", "UTC+5", etc.
  keywords: string[];
}

export const TIMEZONES: TimezoneOption[] = [
  { iana: 'Europe/Kaliningrad', city: 'Калининград', utcOffset: 'UTC+2', keywords: ['калининград', 'kaliningrad'] },
  { iana: 'Europe/Moscow', city: 'Москва', utcOffset: 'UTC+3', keywords: ['москва', 'санкт-петербург', 'питер', 'moscow', 'spb'] },
  { iana: 'Europe/Samara', city: 'Самара', utcOffset: 'UTC+4', keywords: ['самара', 'ижевск', 'тольятти', 'samara'] },
  { iana: 'Asia/Yekaterinburg', city: 'Екатеринбург', utcOffset: 'UTC+5', keywords: ['екатеринбург', 'екат', 'уфа', 'пермь', 'тюмень', 'челябинск', 'yekaterinburg'] },
  { iana: 'Asia/Omsk', city: 'Омск', utcOffset: 'UTC+6', keywords: ['омск', 'omsk'] },
  { iana: 'Asia/Novosibirsk', city: 'Новосибирск', utcOffset: 'UTC+7', keywords: ['новосибирск', 'новосиб', 'томск', 'кемерово', 'барнаул', 'novosibirsk'] },
  { iana: 'Asia/Krasnoyarsk', city: 'Красноярск', utcOffset: 'UTC+7', keywords: ['красноярск', 'норильск', 'krasnoyarsk'] },
  { iana: 'Asia/Irkutsk', city: 'Иркутск', utcOffset: 'UTC+8', keywords: ['иркутск', 'улан-удэ', 'irkutsk'] },
  { iana: 'Asia/Yakutsk', city: 'Якутск', utcOffset: 'UTC+9', keywords: ['якутск', 'чита', 'yakutsk'] },
  { iana: 'Asia/Vladivostok', city: 'Владивосток', utcOffset: 'UTC+10', keywords: ['владивосток', 'хабаровск', 'vladivostok'] },
  { iana: 'Asia/Magadan', city: 'Магадан', utcOffset: 'UTC+11', keywords: ['магадан', 'южно-сахалинск', 'сахалин', 'magadan'] },
  { iana: 'Asia/Kamchatka', city: 'Петропавловск-Камчатский', utcOffset: 'UTC+12', keywords: ['камчатка', 'анадырь', 'петропавловск', 'kamchatka'] },
  // Ближнее зарубежье и популярные
  { iana: 'Europe/Minsk', city: 'Минск', utcOffset: 'UTC+3', keywords: ['минск', 'беларусь', 'minsk'] },
  { iana: 'Asia/Tbilisi', city: 'Тбилиси', utcOffset: 'UTC+4', keywords: ['тбилиси', 'грузия', 'tbilisi'] },
  { iana: 'Asia/Yerevan', city: 'Ереван', utcOffset: 'UTC+4', keywords: ['ереван', 'армения', 'yerevan'] },
  { iana: 'Asia/Baku', city: 'Баку', utcOffset: 'UTC+4', keywords: ['баку', 'азербайджан', 'baku'] },
  { iana: 'Asia/Almaty', city: 'Алматы', utcOffset: 'UTC+5', keywords: ['алматы', 'астана', 'казахстан', 'almaty', 'astana'] },
  { iana: 'Asia/Tashkent', city: 'Ташкент', utcOffset: 'UTC+5', keywords: ['ташкент', 'узбекистан', 'tashkent'] },
  { iana: 'Asia/Dubai', city: 'Дубай', utcOffset: 'UTC+4', keywords: ['дубай', 'оаэ', 'dubai'] },
  { iana: 'Asia/Bangkok', city: 'Бангкок', utcOffset: 'UTC+7', keywords: ['бангкок', 'пхукет', 'таиланд', 'bangkok', 'phuket'] },
  { iana: 'Europe/Berlin', city: 'Берлин', utcOffset: 'UTC+1', keywords: ['берлин', 'германия', 'европа', 'berlin'] },
  { iana: 'Europe/London', city: 'Лондон', utcOffset: 'UTC+0', keywords: ['лондон', 'великобритания', 'london'] },
  { iana: 'America/New_York', city: 'Нью-Йорк', utcOffset: 'UTC-5', keywords: ['нью-йорк', 'сша', 'new york'] },
];

export const POPULAR_TIMEZONE_IANAS = [
  'Europe/Moscow',
  'Asia/Novosibirsk',
  'Europe/Kaliningrad',
];

/** Получить динамическое смещение UTC для IANA-пояса */
export function getTimezoneOffset(iana: string, date: Date = new Date()): string {
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: iana,
      timeZoneName: 'shortOffset',
    });
    const parts = formatter.formatToParts(date);
    const tzPart = parts.find((p) => p.type === 'timeZoneName');
    if (tzPart && tzPart.value.startsWith('GMT')) {
      return tzPart.value.replace('GMT', 'UTC');
    }
  } catch {}
  const match = TIMEZONES.find((t) => t.iana === iana);
  return match ? match.utcOffset : 'UTC';
}

/** Найти пояс в списке */
export function findTimezone(iana: string): TimezoneOption | undefined {
  return TIMEZONES.find((t) => t.iana === iana);
}

/** Форматированная подпись пояса: «Москва, UTC+3» */
export function formatTzLabel(iana: string): string {
  const match = findTimezone(iana);
  const offset = getTimezoneOffset(iana);
  if (match) {
    return `${match.city}, ${offset}`;
  }
  const city = iana.split('/').pop()?.replace(/_/g, ' ') ?? iana;
  return `${city}, ${offset}`;
}

/** Поиск поясов по запросу */
export function searchTimezones(query: string): TimezoneOption[] {
  const clean = query.trim().toLowerCase();
  if (!clean) return [];
  return TIMEZONES.filter((tz) => {
    if (tz.city.toLowerCase().includes(clean)) return true;
    if (tz.iana.toLowerCase().includes(clean)) return true;
    if (tz.utcOffset.toLowerCase().includes(clean)) return true;
    return tz.keywords.some((k) => k.includes(clean));
  });
}
