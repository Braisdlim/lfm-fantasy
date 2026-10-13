// Importaciones estáticas seleccionadas dentro de un módulo cargado bajo demanda.
// Importar los namespaces completos arrastraba todos los tipos de gráfico y componentes.
import { init, use } from 'echarts/core';
import { LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, CanvasRenderer]);
export { init };
