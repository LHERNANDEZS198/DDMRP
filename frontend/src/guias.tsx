import { ReactNode } from 'react'
import { Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material'
import Close from '@mui/icons-material/Close'

/** Ventana de explicación larga (metodología, cómo funciona una pantalla). Se abre desde un botón "¿Cómo funciona?". */
export function Guia({ abierta, cerrar, titulo, children }: { abierta: boolean; cerrar: () => void; titulo: string; children: ReactNode }) {
  return (
    <Dialog open={abierta} onClose={cerrar} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', pr: 1 }}>
        <Box sx={{ flex: 1, fontWeight: 700 }}>{titulo}</Box>
        <IconButton onClick={cerrar} size="small" aria-label="Cerrar"><Close /></IconButton>
      </DialogTitle>
      <DialogContent dividers>{children}</DialogContent>
      <DialogActions><Button onClick={cerrar} variant="contained">Entendido</Button></DialogActions>
    </Dialog>)
}

const H = ({ children }: { children: ReactNode }) => <Typography variant="subtitle1" sx={{ fontWeight: 700, mt: 2.5, mb: .5, color: 'primary.dark' }}>{children}</Typography>
const P = ({ children }: { children: ReactNode }) => <Typography variant="body2" sx={{ mb: 1 }}>{children}</Typography>
const L = ({ items }: { items: ReactNode[] }) => <Box component="ul" sx={{ m: 0, mb: 1, pl: 3, '& li': { fontSize: 14, mb: .5 } }}>{items.map((x, i) => <li key={i}>{x}</li>)}</Box>
const Clase = ({ c, color }: { c: string; color: string }) => <Chip size="small" label={c} sx={{ bgcolor: color, color: '#fff', fontWeight: 700, minWidth: 28 }} />

const COLOR: Record<string, string> = { A: '#2e7d32', B: '#f9a825', C: '#9e9e9e', N: '#1565c0', D: '#6d4c41', S: '#8e24aa' }

/** Metodología de la clasificación ABC × XYZ: cómo se calcula cada cosa y cómo leerla. `meta` trae los cortes y la ventana que se están usando. */
export function GuiaClasificacion({ abierta, cerrar, meta }: { abierta: boolean; cerrar: () => void; meta: any }) {
  const a = meta?.corte_a ?? 80; const b = meta?.corte_b ?? 95; const [x, y] = meta?.cortes_iv ?? [0.5, 0.8]
  const meses = meta?.meses ?? 12
  return (
    <Guia abierta={abierta} cerrar={cerrar} titulo="Cómo se clasifican los items (ABC × XYZ)">
      <P>La clasificación responde dos preguntas distintas sobre cada item: <b>¿cuánto aporta?</b> (letra ABC) y <b>¿qué tan predecible es su venta?</b> (letra XYZ).
        Juntas dan una clase como <b>AX</b> (aporta mucho y se vende parejo) o <b>CZ</b> (aporta poco y se vende a saltos). Sirve para decidir dónde poner la atención y el capital.</P>

      <H>1 · ABC: cuánto aporta</H>
      <P>Se toma la venta de la ventana elegida (hoy {meses} meses), se ordenan los items de mayor a menor según el criterio y se va acumulando el porcentaje del total:</P>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 1 }}>
        <Box><Clase c="A" color={COLOR.A} /> los que juntan hasta el <b>{a} %</b> acumulado</Box>
        <Box><Clase c="B" color={COLOR.B} /> hasta el <b>{b} %</b></Box>
        <Box><Clase c="C" color={COLOR.C} /> el resto de la cola</Box>
      </Box>
      <L items={[
        <>El item que <b>cruza</b> el corte se queda en la clase mejor (si con él se pasa del {a} %, igual es A).</>,
        <>Un item con valor cero o negativo (margen ≤ 0) va a <b>C</b>: no aporta.</>,
        <>Los cortes ({a} y {b}) se pueden cambiar arriba; por defecto 80 / 95 (regla de Pareto).</>,
      ]} />
      <P><b>Criterio (“ABC según”):</b></P>
      <L items={[
        <><b>Margen bruto $</b> (recomendado): venta neta − unidades × costo. Un item puede vender muchísimo y dejar casi nada; el margen mide lo que realmente queda.</>,
        <><b>Venta neta $:</b> solo cuánto se facturó, sin IVA.</>,
        <><b>Consumo a costo $:</b> unidades vendidas × costo; cuánto capital “consume” el item.</>,
      ]} />
      <P><b>Venta neta</b> = valor bruto − descuentos de línea − descuentos globales, <b>sin IVA</b>; las devoluciones restan. <b>Costo</b> = costo promedio <i>actual</i> del item en Siesa (por instalación).</P>
      <P><b>Nivel:</b> “Por item” suma las tiendas que dejaste filtradas y da una sola clase por item; “Por tienda × item” clasifica cada item dentro de cada tienda (un mismo item puede ser A en una tienda y C en otra).</P>

      <H>2 · XYZ: qué tan predecible es</H>
      <P>Usa el <b>IV (índice de variabilidad)</b> que ya calcula el motor DDMRP: la desviación de la venta mensual dividida entre su promedio. Cuanto más alto, más a saltos se vende.
        A nivel item es el IV de sus tiendas, ponderado por la venta diaria (ADU) de cada una.</P>
      <L items={[
        <><b>X · estable:</b> IV menor que {x}. Se puede planear con confianza.</>,
        <><b>Y · media:</b> IV hasta {y}. Variación moderada.</>,
        <><b>Z · variable:</b> IV mayor que {y}. Venta errática: exige más colchón o más seguimiento.</>,
        <><b>Sin letra</b> (ej. solo “A”): no hay IV calculado todavía (item sin buffer en el motor).</>,
      ]} />
      <Typography variant="caption" color="text.secondary">Los cortes de X, Y y Z salen de la tabla de factores VAR (Maestros → Factores): si la cambias, la clasificación se mueve con ella.</Typography>

      <H>3 · Apartes: los que no entran al ranking</H>
      <P>Para no ensuciar el ABC, tres grupos se separan antes de rankear (se evalúan en este orden):</P>
      <Table size="small" sx={{ mb: 1 }}>
        <TableHead><TableRow><TableCell width={70}>Clase</TableCell><TableCell>Qué es</TableCell><TableCell>Qué hacer</TableCell></TableRow></TableHead>
        <TableBody>
          <TableRow><TableCell><Clase c="D" color={COLOR.D} /></TableCell><TableCell><b>Sin venta</b> en la ventana (ni unidades ni valor).</TableCell><TableCell>Mira su inventario a costo: si tiene stock es capital dormido.</TableCell></TableRow>
          <TableRow><TableCell><Clase c="N" color={COLOR.N} /></TableCell><TableCell><b>Nuevo:</b> su primera venta fue en los últimos 3 meses{meta?.nuevo_desde ? ` (desde ${meta.nuevo_desde})` : ''}; aún no tiene historia para juzgarlo. Solo aplica con ventanas de 6 meses o más.</TableCell><TableCell>Seguirlo de cerca; clasificará cuando acumule historia.</TableCell></TableRow>
          <TableRow><TableCell><Clase c="S" color={COLOR.S} /></TableCell><TableCell><b>Sin costo</b> en Siesa: no se puede calcular el margen (solo cuando el criterio usa costo).</TableCell><TableCell>Corregir el costo en Siesa o clasificar por Venta neta.</TableCell></TableRow>
        </TableBody>
      </Table>

      <H>4 · Cómo leer la clase (ABC × XYZ)</H>
      <P>Lectura habitual de la matriz; úsala como guía, no como regla fija:</P>
      <Table size="small" sx={{ mb: 1, '& td, & th': { verticalAlign: 'top' } }}>
        <TableHead><TableRow><TableCell></TableCell><TableCell>X · estable</TableCell><TableCell>Y · media</TableCell><TableCell>Z · variable</TableCell></TableRow></TableHead>
        <TableBody>
          <TableRow><TableCell><Clase c="A" color={COLOR.A} /></TableCell><TableCell>Nunca debe faltar. Buffer ajustado y reposición frecuente.</TableCell><TableCell>Vigilar de cerca: pesa mucho y se mueve algo.</TableCell><TableCell>Alto riesgo: aporta mucho pero es errático. Revisar pronóstico, promociones y colchón.</TableCell></TableRow>
          <TableRow><TableCell><Clase c="B" color={COLOR.B} /></TableCell><TableCell>Gestión normal.</TableCell><TableCell>Gestión normal, revisar de vez en cuando.</TableCell><TableCell>Revisar si el buffer sigue sirviendo.</TableCell></TableRow>
          <TableRow><TableCell><Clase c="C" color={COLOR.C} /></TableCell><TableCell>Poco valor y parejo: automatizar con inventario mínimo.</TableCell><TableCell>Poco valor: no sobrestockear.</TableCell><TableCell>Poco valor y errático: candidato a bajar inventario, pedir bajo demanda o descontinuar.</TableCell></TableRow>
        </TableBody>
      </Table>

      <H>5 · Otras columnas</H>
      <L items={[
        <><b>Clase vs Clase global:</b> “Clase” se calcula solo con lo que dejaste filtrado (ej. una tienda, un laboratorio): es el ABC <i>dentro de ese grupo</i>. “Clase global” es la que tendría con todo lo que puedes ver, sin los filtros de pantalla; úsala para saber qué tan importante es de verdad.</>,
        <><b>Margen %:</b> margen ÷ venta neta.</>,
        <><b>% acum.:</b> porcentaje acumulado del criterio hasta ese item; define A, B y C.</>,
        <><b>Inv. a costo $:</b> inventario actual × costo promedio. Es el dinero parado en stock.</>,
        <><b>GMROI:</b> margen anualizado ÷ inventario a costo: cuántos pesos de margen deja cada peso invertido en inventario durante un año. Más alto es mejor; por debajo de 1 el margen anual no alcanza a cubrir lo invertido en stock.</>,
        <><b>Días inv.:</b> inventario ÷ venta diaria promedio de la ventana: para cuántos días alcanza el stock.</>,
      ]} />

      <Alert severity="info" sx={{ mt: 2 }}>
        <b>Para tener en cuenta:</b> el costo es el promedio <i>actual</i> (no el de cada venta), así que el margen es una aproximación; las ventas cargadas a mano por Excel no traen valor en pesos, por eso el ABC por margen o venta solo es confiable con ventas traídas de Siesa;
        y la ventana ({meses} meses) cambia el resultado: una de 12 meses suaviza la estacionalidad, una de 3 refleja mejor lo reciente.
      </Alert>
    </Guia>)
}

const PEND = '#757575'; const APRO = '#1565c0'; const ENV = '#2e7d32'

/** Cómo funcionan los estados de la Matriz de despacho y por qué se reinician al correr el motor. */
export function GuiaDespacho({ abierta, cerrar }: { abierta: boolean; cerrar: () => void }) {
  return (
    <Guia abierta={abierta} cerrar={cerrar} titulo="Pendientes, Aprobadas y Enviadas">
      <P>Cada vez que corre el motor DDMRP (la corrida nocturna, “Recalcular solo motor” o “ETL + motor completo” en el menú Motor DDMRP) genera una <b>corrida nueva</b> con las sugerencias de envío de todas las tiendas.
        La matriz siempre trabaja sobre la <b>última corrida</b>, y cada fila de esa corrida pasa por tres estados:</P>
      <Table size="small" sx={{ mb: 1, '& td': { verticalAlign: 'top' } }}>
        <TableHead><TableRow><TableCell width={120}>Estado</TableCell><TableCell>Qué significa</TableCell><TableCell>Cómo llega ahí</TableCell></TableRow></TableHead>
        <TableBody>
          <TableRow><TableCell><Chip size="small" label="PENDIENTE" sx={{ bgcolor: PEND, color: '#fff', fontWeight: 700 }} /></TableCell>
            <TableCell>Lo que sugiere el motor; nadie lo ha revisado. Aquí puedes ajustar la columna <b>A enviar</b> (por defecto es lo asignado).</TableCell>
            <TableCell>Todas las filas nacen así en cada corrida.</TableCell></TableRow>
          <TableRow><TableCell><Chip size="small" label="APROBADA" sx={{ bgcolor: APRO, color: '#fff', fontWeight: 700 }} /></TableCell>
            <TableCell>Revisada y lista para despachar, con la cantidad que dejaste en <b>A enviar</b>. Es lo único que entra al archivo plano de Siesa. Se puede <b>devolver a pendiente</b> si te arrepientes.</TableCell>
            <TableCell>“Aprobar seleccionados” desde Pendientes.</TableCell></TableRow>
          <TableRow><TableCell><Chip size="small" label="ENVIADA" sx={{ bgcolor: ENV, color: '#fff', fontWeight: 700 }} /></TableCell>
            <TableCell>Ya salió: el plano se generó o la fila se dio por despachada. Sale de Pendientes y de Aprobadas y ya no se puede devolver.</TableCell>
            <TableCell>“Generar archivo plano Siesa” con <i>Marcar como enviadas</i>, o el botón “Marcar como enviadas” en Aprobadas.</TableCell></TableRow>
        </TableBody>
      </Table>
      <P>Flujo habitual: <b>Pendientes → Aprobar → Aprobadas → Generar plano (marcando enviadas) → Enviadas</b>. Las tiendas cuyo despacho vale menos del mínimo configurado no se envían ni entran al plano.</P>

      <Alert severity="warning" sx={{ my: 2 }}>
        <b>Los estados se borran cuando el motor corre de nuevo.</b> Las aprobaciones y los envíos viven dentro de la corrida en que se hicieron. Al correr el motor otra vez
        (de noche, “Recalcular solo motor” o “ETL + motor completo”) se crea una corrida nueva y <b>todo vuelve a PENDIENTE</b>: las Aprobadas y las Enviadas ya no aparecen en la matriz.
        No se heredan; la corrida anterior solo se conserva unos días para consulta y auditoría.
      </Alert>
      <P><b>Qué implica en la práctica:</b></P>
      <L items={[
        <>Aprueba y genera el plano <b>en la misma sesión</b>, antes de volver a correr el motor. No corras el motor entre aprobar y bajar el plano: perderías las aprobaciones.</>,
        <>Lo que ya enviaste <b>vuelve a salir como pendiente</b> en la corrida siguiente mientras el motor no “vea” esa mercancía. Si ya creaste el traslado en Siesa, el siguiente ETL lo trae como <b>tránsito</b> y el motor deja de sugerirlo (mientras la regla “Contar traslados abiertos” esté en Sí); si el traslado aún no existe, la sugerencia reaparece.</>,
        <>Por eso el archivo plano que descargas es el registro real de lo enviado: guárdalo, no confíes en que la matriz recuerde lo despachado.</>,
        <>La corrida nocturna también reinicia los estados: lo que no despachaste ayer aparece de nuevo en pendientes con las cifras de hoy.</>,
      ]} />
      <H>¿Trabajas el DÍA 1 en la mañana y el DÍA 2 en la tarde?</H>
      <L items={[
        <>Termina el DÍA 1: aprueba, genera el plano marcando enviadas y <b>cárgalo en Siesa</b> (si el traslado no existe, el CEDI sigue viéndose lleno).</>,
        <>Antes del DÍA 2 corre <b>Motor DDMRP → Recalcular ahora</b> y, en la ventana que abre, deja elegido <b>solo el DÍA 2</b> en el reparto del CEDI. Así las tiendas del DÍA 1 no compiten por el stock que quedó.</>,
        <>Elige la corrida del DÍA 2 aquí. Las tiendas del DÍA 1 vuelven a salir en Pendientes: no las apruebes otra vez.</>,
        <>Si el reparto del CEDI de la mañana ya incluía los DÍAs 1 + 2, puedes seguir sin recalcular y no pierdes lo aprobado.</>,
      ]} />
    </Guia>)
}
