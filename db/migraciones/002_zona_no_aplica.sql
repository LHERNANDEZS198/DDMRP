-- Zona «No aplica» (sin buffer = sin ADU, y sin stock): antes el motor la marcaba VERDE. Correr UNA vez, con psql (autocommit), DESPUES de desplegar el backend nuevo
-- (que ya agrega el valor al arrancar) y ANTES o DESPUES del primer motor nuevo: da igual, el motor nuevo ya escribe NO_APLICA.
-- Las combinaciones sin buffer pero CON stock siguen en EXCESO (capital sin demanda, gestionable): no se tocan.

-- 1) el valor del enum (si el backend ya arranco, ya existe y esta sentencia no hace nada)
ALTER TYPE ddmrp.zona_buffer ADD VALUE IF NOT EXISTS 'NO_APLICA';

-- 2) la historia, dia por dia (un solo UPDATE gigante bloquea y llena el log de la base; asi cada dia confirma por separado)
DO $$
DECLARE f date;
BEGIN
  FOR f IN SELECT DISTINCT fecha FROM ddmrp.buffer_historia ORDER BY 1 LOOP
    UPDATE ddmrp.buffer_historia SET zona = 'NO_APLICA' WHERE fecha = f AND zona = 'VERDE' AND COALESCE(tog_aj, 0) <= 0;
    COMMIT;
  END LOOP;
END $$;

-- 3) la ultima corrida de cada motor (hasta que corra el motor nuevo, para que las pantallas ya lo muestren)
UPDATE ddmrp.sugerencias_envio SET zona = 'NO_APLICA' WHERE zona = 'VERDE' AND COALESCE(tog_aj, 0) <= 0;
UPDATE ddmrp.sugerencias_cedi  SET zona = 'NO_APLICA' WHERE zona = 'VERDE' AND COALESCE(tog_aj, 0) <= 0;

-- 4) comprobacion: sin_buffer_verde debe quedar en 0
SELECT count(*) FILTER (WHERE COALESCE(tog_aj, 0) <= 0 AND zona = 'VERDE') AS sin_buffer_verde,
       count(*) FILTER (WHERE zona = 'NO_APLICA') AS no_aplica
FROM ddmrp.sugerencias_envio
WHERE ejecucion_id = ANY (SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado = 'ok' GROUP BY empresa);

-- Despues: en Indicadores de compras pulsar «Recalcular» (rehace los dias con zona de cada mes sin contar NO_APLICA).
