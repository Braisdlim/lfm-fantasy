// Qué job toca disparar, decidido en **hora de Madrid**.
//
// El mercado de la liga rota a las 19:21 hora española, no a una hora UTC fija: en verano son las
// 17:21 UTC y en invierno las 18:21. Cloudflare solo programa en UTC, así que el cron dispara el
// Worker a las dos horas candidatas y es este código el que decide, mirando la hora local, si
// estamos de verdad en una de las dos ventanas que importan.
//
// Los dos momentos que deciden (docs/plan-app.md):
//
//   1. **Justo antes del cierre**: el recuento final de pujas, que es con lo que decides.
//   2. **Justo después de la rotación**: mercado nuevo, recomendaciones nuevas.
//
// Y desde el 2026-09-16, tambien red de seguridad horaria. Medido esa semana: de las 17 pasadas
// horarias que GitHub tiene programadas, **llegaron unas 5 al dia**. El resultado es que el mercado
// se quedaba horas sin actualizar y con el las recomendaciones. Como el job ligero sale con
// `--skip-if-recent`, un disparo de mas no gasta ni una peticion a la API: el primero que llega
// hace el trabajo y los demas salen solos.

export const MARKET_CLOSE_MADRID = { hour: 19, minute: 21 };
export const WINDOW_MINUTES = 20;

// Horas de Madrid en las que tiene sentido refrescar el mercado. De madrugada no cambia nada y la
// alineacion ya esta decidida, asi que no merece gastar minutos de Actions.
export const BACKSTOP_FROM = 8;
export const BACKSTOP_TO = 23;
export const BACKSTOP_MINUTE = 15;
export const VALUES_MINUTE_FROM = 20;

/** Hora y minuto en Madrid, resolviendo el horario de verano por nosotros. */
export function madridTime(date) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Madrid',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const get = (type) => Number(parts.find((p) => p.type === type).value);
  return { hour: get('hour') % 24, minute: get('minute') };
}

// Reintentos del diario después de la ventana del cierre. LaLiga a veces tarda horas en publicar
// el mercado nuevo, y hasta el 2026-09-20 el único disparo puntual del diario era el de las 19:25:
// si llegaba antes que LaLiga, la app pasaba la tarde con el mercado cerrado. El propio job ya
// espera 20 minutos dentro de la ejecución; esto cubre los retrasos largos. Van con
// `skip_if_recent`, así que si el diario ya recogió el ciclo nuevo salen sin gastar una petición.
export const DAILY_RETRY_UNTIL_MINUTES = 200; // hasta ~22:40 de Madrid
export const DAILY_RETRY_MINUTES = [20, 30]; // el segundo despertar de la hora (:25), y solo ese

/**
 * Qué disparar y cómo. `skipIfRecent` pide al job que salga sin trabajar si ya se hizo.
 * @returns {{ job: 'light' | 'daily', skipIfRecent: boolean } | null}
 */
export function planFor(date) {
  const { hour, minute } = madridTime(date);
  const now = hour * 60 + minute;
  const close = MARKET_CLOSE_MADRID.hour * 60 + MARKET_CLOSE_MADRID.minute;
  if (now < close && now >= close - WINDOW_MINUTES) return { job: 'light', skipIfRecent: false };
  if (now > close && now <= close + WINDOW_MINUTES) return { job: 'daily', skipIfRecent: false };
  if (now > close && now <= close + DAILY_RETRY_UNTIL_MINUTES && minute >= DAILY_RETRY_MINUTES[0] && minute < DAILY_RETRY_MINUTES[1]) {
    return { job: 'daily', skipIfRecent: true };
  }
  if (hour >= BACKSTOP_FROM && hour < BACKSTOP_TO && minute < BACKSTOP_MINUTE) {
    return { job: 'light', skipIfRecent: false };
  }
  // Valores nuevos: LaLiga los cambia a las 00:15. Una pasada ligera a las 00:25 y otra a la 01:25
  // los recoge en cuanto salen (el job pide /players solo si aún no tiene los del día y comprueba
  // que de verdad hayan cambiado). Antes llegaban con el diario, 19 horas tarde.
  if ((hour === 0 || hour === 1) && minute >= VALUES_MINUTE_FROM && minute < VALUES_MINUTE_FROM + 10) {
    return { job: 'light', skipIfRecent: false };
  }
  return null;
}

/**
 * `light` antes del cierre, `daily` después de la rotación, `null` el resto del tiempo.
 * Devolver `null` es lo normal: el cron dispara el Worker más veces de las que hay que trabajar,
 * porque sale más barato comprobar la hora aquí que mantener dos crones por horario estacional.
 */
export function jobFor(date) {
  return planFor(date)?.job ?? null;
}
