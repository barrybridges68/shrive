var options = {
  chart: {
    height: 350,
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
      columnWidth: '40%',
      borderRadius: 3,
    },
  },
  dataLabels: {
    enabled: false
  },
  stroke: {
    show: true,
    width: 0,
    colors: ["#682cb1", "#e1204d", "#548b0f", "#d59600", "#2d3ebc", "#3e3e42", "#e91964"]
  },
  series: [{
    name: 'Projects',
    data: [14, 10, 8, 2, 3, 5, 4]
  }],
  legend: {
    show: false,
  },
  xaxis: {
    categories: ['Total', 'Not Started', 'In Progress', 'On Hold', 'Cancelled', 'Finished', 'Pending'],
  },
  yaxis: {
    show: false,
  },
  fill: {
    colors: ["#682cb1", "#e1204d", "#548b0f", "#d59600", "#2d3ebc", "#3e3e42", "#e91964"],
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
  document.querySelector("#projects"),
  options
);
chart.render();



















