import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DashboardPanel from '@/components/DashboardPanel.vue'
import { createTestVuetify } from '@/test/helpers'
import type { DashboardPanel as PanelData } from '@/types'

const ORANGE = '#f59e0b'
const TEAL = '#0d9488'

vi.mock('vue-echarts', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'VChartStub',
      props: { option: { type: Object, required: true } },
      setup: () => () => h('div'),
    }),
  }
})

const numericalData = {
  buckets: [
    { range_start: 0, range_end: 1, count: 3 },
    { range_start: 1, range_end: 2, count: 5, is_overflow: true },
  ],
  statistics: { mean: 1, median: 1, std: 0.1, min: 0, max: 2, count: 8 },
}

const categoricalData = {
  categories: [
    { value: 'class_0', count: 3, percentage: 37.5 },
    { value: 'class_1', count: 5, percentage: 62.5 },
  ],
  statistics: { unique_count: 2, total_count: 8, top_value: 'class_1', null_count: 0 },
}

function makePanel(direction: 'input' | 'output', dataType: 'numerical' | 'categorical'): PanelData {
  const numerical = dataType === 'numerical'
  return {
    field_name: 'field',
    direction,
    data_type: dataType,
    chart_type: numerical ? 'histogram' : 'bar',
    data: (numerical ? numericalData : categoricalData) as PanelData['data'],
    latest_drift: null,
  }
}

function barColors(panel: PanelData): string[] {
  const wrapper = mount(DashboardPanel, {
    props: { panel },
    global: { plugins: [createTestVuetify()] },
  })
  const option = wrapper.findComponent({ name: 'VChartStub' }).props('option') as {
    series: { data: { itemStyle: { color: string; borderColor?: string } }[] }[]
  }
  return option.series[0]!.data.map((d) => d.itemStyle.borderColor ?? d.itemStyle.color)
}

describe('DashboardPanel chart colors', () => {
  it.each(['numerical', 'categorical'] as const)('renders output (%s) charts in orange', (dataType) => {
    expect(new Set(barColors(makePanel('output', dataType)))).toEqual(new Set([ORANGE]))
  })

  it.each(['numerical', 'categorical'] as const)('renders input (%s) charts in teal', (dataType) => {
    expect(new Set(barColors(makePanel('input', dataType)))).toEqual(new Set([TEAL]))
  })
})

describe('DashboardPanel log scale', () => {
  type Axis = { type: string }
  type Option = { xAxis: Axis; yAxis: Axis; series: { data: ({ value: number | null } | number)[] }[] }

  function chartOption(panel: PanelData, logScale?: boolean): Option {
    const wrapper = mount(DashboardPanel, {
      props: { panel, logScale },
      global: { plugins: [createTestVuetify()] },
    })
    return wrapper.findComponent({ name: 'VChartStub' }).props('option') as Option
  }

  it.each(['numerical', 'categorical'] as const)('uses a log count axis for %s charts', (dataType) => {
    expect(chartOption(makePanel('input', dataType), true).yAxis.type).toBe('log')
  })

  it('keeps the linear count axis by default', () => {
    expect(chartOption(makePanel('input', 'numerical')).yAxis.type).toBe('value')
  })

  it('leaves out empty buckets on the log axis', () => {
    const panel = makePanel('input', 'numerical')
    panel.data = {
      ...numericalData,
      buckets: [
        { range_start: 0, range_end: 1, count: 0 },
        { range_start: 1, range_end: 2, count: 7 },
      ],
    } as unknown as PanelData['data']
    expect(chartOption(panel, true).series[0]!.data).toMatchObject([{ value: null }, { value: 7 }])
  })

  it('puts the log axis on x for horizontal bar charts', () => {
    const panel = makePanel('input', 'categorical')
    panel.data = {
      ...categoricalData,
      categories: [{ value: 'a very long category label', count: 3, percentage: 100 }],
    } as unknown as PanelData['data']
    const option = chartOption(panel, true)
    expect(option.xAxis.type).toBe('log')
    expect(option.yAxis.type).toBe('category')
  })
})
