var options = {
  chart: {
    height: 240,
    width: '100%',
    type: 'bar',
    toolbar: {
      show: false,
    },
  },
  plotOptions: {
    bar: {
      horizontal: false,
      distributed: true,
      columnWidth: '50%',
      borderRadius: 10,
    },
  },
  dataLabels: {
    enabled: false
  },
  stroke: {
    show: true,
    width: 0,
    colors: ["#338dd7", "#3a97e0", "#42a1e9", "#4aabf2", "#52b5fb"]
  },
  series: [{
    name: 'Leads',
    data: [2000, 4000, 8000, 12000, 9000, 5000, 3000]
  }],
  legend: {
    show: false,
  },
  xaxis: {
    categories: ['1M', '2M', '5M', '10M', '20M', '50M', '100M'],
  },
  yaxis: {
    show: false,
  },
  fill: {
    colors: ["#338dd7", "#3a97e0", "#42a1e9", "#4aabf2", "#52b5fb"],
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return + val
      }
    }
  },
  grid: {
    show: false,
    xaxis: {
      lines: {
        show: true
      }
    },
    yaxis: {
      lines: {
        show: false,
      }
    },
  },
  colors: ['#ffffff'],
}
var chart = new ApexCharts(
  document.querySelector("#source"),
  options
);
chart.render();