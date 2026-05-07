var options = {
  chart: {
    height: 190,
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
      borderRadius: 4,
    },
  },
  dataLabels: {
    enabled: false
  },
  stroke: {
    show: true,
    width: 0,
  },
  series: [{
    name: 'Sales',
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
    colors: ["#1AD9FF", "#3DDFEA", "#5FE6D4", "#82ECBF", "#A5F2A9", "#C7F994", "#EAFF7E"],
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return + val
      },
    },
    theme: 'dark',
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
  document.querySelector("#sales"),
  options
);
chart.render();