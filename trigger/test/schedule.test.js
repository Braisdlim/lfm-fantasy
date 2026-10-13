// node --test
//
// El horario de verano es exactamente donde esto se rompería sin darnos cuenta, así que cada caso
// se comprueba en verano (UTC+2) y en invierno (UTC+1).

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { jobFor, madridTime, planFor } from '../src/schedule.js';

const utc = (iso) => new Date(iso);

test('lee la hora de Madrid en verano y en invierno', () => {
  assert.deepEqual(madridTime(utc('2026-09-09T17:05:00Z')), { hour: 19, minute: 5 }); // UTC+2
  assert.deepEqual(madridTime(utc('2026-12-09T18:05:00Z')), { hour: 19, minute: 5 }); // UTC+1
});

test('en verano dispara light antes del cierre y daily después', () => {
  assert.equal(jobFor(utc('2026-09-09T17:05:00Z')), 'light'); // 19:05 Madrid
  assert.equal(jobFor(utc('2026-09-09T17:25:00Z')), 'daily'); // 19:25 Madrid
});

test('en invierno la misma hora local cae en otra hora UTC y sigue funcionando', () => {
  assert.equal(jobFor(utc('2026-12-09T18:05:00Z')), 'light'); // 19:05 Madrid
  assert.equal(jobFor(utc('2026-12-09T18:25:00Z')), 'daily'); // 19:25 Madrid
  // La hora UTC que en verano era la ventana, en invierno ya no lo es: cae en la red de
  // seguridad horaria, que dispara una pasada ligera igualmente pero sin ser el momento clave.
  assert.equal(jobFor(utc('2026-12-09T17:05:00Z')), 'light'); // 18:05 Madrid
  assert.equal(jobFor(utc('2026-12-09T17:25:00Z')), null); // 18:25, segundo despertar de la hora
});

test('el segundo despertar de cada hora no repite trabajo', () => {
  // El cron dispara a :05 y a :25. Fuera de la ventana del cierre, solo el primero trabaja.
  assert.equal(jobFor(utc('2026-09-09T18:05:00Z')), 'light'); // 20:05 Madrid
  assert.equal(jobFor(utc('2026-09-09T10:25:00Z')), null); // 12:25 Madrid
  assert.equal(jobFor(utc('2026-09-09T09:00:00Z')), 'light'); // 11:00 Madrid
});

test('el instante exacto del cierre no dispara ninguno de los dos', () => {
  // A las 19:21 el mercado está rotando: pedir datos justo ahí devuelve una foto a medias.
  assert.equal(jobFor(utc('2026-09-09T17:21:00Z')), null);
});

test('los bordes de las ventanas son los esperados', () => {
  assert.equal(jobFor(utc('2026-09-09T17:01:00Z')), 'light'); // 19:01, veinte minutos antes
  // 19:00 no es todavía la ventana del cierre, pero sí la pasada horaria de esa hora.
  assert.equal(jobFor(utc('2026-09-09T17:00:00Z')), 'light');
  assert.equal(jobFor(utc('2026-09-09T17:41:00Z')), 'daily'); // 19:41, veinte minutos después
  assert.equal(jobFor(utc('2026-09-09T17:42:00Z')), null); // 19:42, ya no, y pasado el minuto 15
});

test('el cambio de hora de octubre no deja el día sin disparo', () => {
  // El último domingo de octubre España pasa de UTC+2 a UTC+1 de madrugada, lejos de la ventana.
  assert.equal(jobFor(utc('2026-10-25T18:05:00Z')), 'light'); // ya en UTC+1: 19:05 Madrid
  assert.equal(jobFor(utc('2026-10-24T17:05:00Z')), 'light'); // víspera en UTC+2: 19:05 Madrid
});

test('la red de seguridad dispara una pasada ligera por hora durante el día', () => {
  // GitHub solo dispara unas 5 de las 17 pasadas horarias que tiene programadas.
  assert.equal(jobFor(new Date('2026-09-16T08:07:00+02:00')), 'light');
  assert.equal(jobFor(new Date('2026-09-16T14:10:00+02:00')), 'light');
  // El segundo despertar de la hora no repite trabajo
  assert.equal(jobFor(new Date('2026-09-16T14:27:00+02:00')), null);
  // De madrugada no se gasta nada: ni el mercado cambia ni queda alineación que decidir
  assert.equal(jobFor(new Date('2026-09-16T03:07:00+02:00')), null);
  assert.equal(jobFor(new Date('2026-09-16T23:07:00+02:00')), null);
});

test('las ventanas del cierre siguen mandando sobre la red de seguridad', () => {
  assert.equal(jobFor(new Date('2026-09-16T19:05:00+02:00')), 'light');
  assert.equal(jobFor(new Date('2026-09-16T19:25:00+02:00')), 'daily');
});

test('tras el cierre, el diario se reintenta cada hora si LaLiga no ha rotado', () => {
  // 19:25 es el disparo puntual: siempre trabaja.
  assert.deepEqual(planFor(new Date('2026-09-16T19:25:00+02:00')), { job: 'daily', skipIfRecent: false });
  // 20:25, 21:25 y 22:25: reintentos que salen solos si ya se recogió el ciclo nuevo.
  for (const h of ['20:25', '21:25', '22:25']) {
    assert.deepEqual(planFor(new Date(`2026-09-16T${h}:00+02:00`)), { job: 'daily', skipIfRecent: true });
  }
  // En invierno igual, en otra hora UTC.
  assert.deepEqual(planFor(utc('2026-12-09T19:25:00Z')), { job: 'daily', skipIfRecent: true }); // 20:25
  // El :05 de esas horas sigue siendo la pasada ligera.
  assert.deepEqual(planFor(new Date('2026-09-16T21:05:00+02:00')), { job: 'light', skipIfRecent: false });
  // Pasada la ventana de reintentos, nada.
  assert.equal(planFor(new Date('2026-09-16T22:45:00+02:00')), null);
});

test('recoge los valores nuevos justo después de las 00:15 de Madrid', () => {
  // verano: 22:25 UTC = 00:25 y 23:25 UTC = 01:25 de Madrid
  assert.deepEqual(planFor(utc('2026-09-19T22:25:00Z')), { job: 'light', skipIfRecent: false });
  assert.deepEqual(planFor(utc('2026-09-19T23:25:00Z')), { job: 'light', skipIfRecent: false });
  // invierno: 23:25 UTC = 00:25 de Madrid
  assert.deepEqual(planFor(utc('2026-12-09T23:25:00Z')), { job: 'light', skipIfRecent: false });
  // el :05 de esas horas no hace nada: es antes de que LaLiga cambie los valores
  assert.equal(planFor(utc('2026-09-19T22:05:00Z')), null);
});
