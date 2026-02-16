import { onMounted, onUnmounted, type Ref } from 'vue'
import * as echarts from 'echarts'

/**
 * Composable for managing ECharts instances with automatic resize handling and cleanup.
 *
 * @param chartRef - Ref to the HTML element that will contain the chart
 * @returns Object with chart management functions
 */
export function useECharts(chartRef: Ref<HTMLElement | null>) {
  let chart: echarts.ECharts | null = null

  /**
   * Initialize the chart instance if it doesn't exist.
   * @returns The chart instance or null if the ref is not available
   */
  const initChart = (): echarts.ECharts | null => {
    if (chartRef.value && !chart) {
      chart = echarts.init(chartRef.value)
    }
    return chart
  }

  /**
   * Get the current chart instance without initializing.
   */
  const getChart = (): echarts.ECharts | null => chart

  /**
   * Set chart options with optional merge behavior.
   * Initializes the chart if needed.
   */
  const setOption = (option: echarts.EChartsOption, notMerge = true): void => {
    if (!chart) {
      initChart()
    }
    chart?.setOption(option, notMerge)
  }

  /**
   * Clear the chart content without disposing it.
   */
  const clear = (): void => {
    chart?.clear()
  }

  /**
   * Handle window resize by resizing the chart.
   */
  const handleResize = (): void => {
    chart?.resize()
  }

  onMounted(() => {
    window.addEventListener('resize', handleResize)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
    chart?.dispose()
    chart = null
  })

  return {
    initChart,
    getChart,
    setOption,
    clear,
    handleResize,
  }
}
