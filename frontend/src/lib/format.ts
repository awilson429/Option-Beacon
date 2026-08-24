export const money = (value?: number | null, digits = 2) => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
export const number = (value?: number | null, digits = 2) => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
export const percent = (value?: number | null) => value == null ? "Unavailable" : `${number(value, 1)}%`;
export const compact = (value?: number | null) => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
export const label = (value?: string | null) => value ? value.replaceAll("_", " ") : "Unavailable";
export const timestamp = (value?: string | null) => value ? new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short" }).format(new Date(value)) : "No update recorded";
