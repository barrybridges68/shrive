var options = {
  series: [{
    name: 'Visitors',
    type: 'area',
    data: [70, 80, 90, 80, 90, 80, 90, 80, 90, 80, 90, 80]
  }, {
    name: 'Conversions',
    type: 'bar',
    data: [60, 70, 80, 70, 80, 70, 80, 70, 80, 70, 80, 70]
  }, {
    name: 'Revenue',
    type: 'bar',
    data: [50, 60, 70, 60, 70, 60, 70, 60, 70, 60, 70, 60]
  }],
  chart: {
    height: 360,
    type: 'area',
    toolbar: {
      show: false
    },
    sparkline: {
      enabled: false,
    },
  },
  plotOptions: {
    bar: {
      columnWidth: '50%',
      borderRadius: 6,
    }
  },
  colors: ["#5fb1f4", "#a186e4"],
  dataLabels: {
    enabled: false
  },
  stroke: {
    curve: 'smooth',
    width: 3,
  },
  yaxis: {
    show: true,
    labels: {
      show: true,
      minWidth: 19,
      maxWidth: 19,
      offsetX: -5,
    },
  },
  legend: {
    show: true,
    offsetY: 10,
    itemMargin: {
      horizontal: 10,
      vertical: 10,
    },
  },
  xaxis: {
    labels: {
      minHeight: 22,
      maxHeight: 22,
      show: true,
    },
    lines: {
      show: false,
    },
    categories: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  },
  grid: {
    show: false,
  },
  fill: {
    type: 'gradient',
    gradient: {
      shade: 'dark',
      type: "vertical",
      shadeIntensity: 0,
      gradientToColors: undefined,
      inverseColors: true,
      opacityFrom: .4,
      opacityTo: .1,
      stops: [0, 50, 80],
      colors: ["#5fb1f4", "#a186e4"]
    }
  },
  tooltip: {
    y: {
      formatter: function (val) {
        return val;
      },
    },
    theme: 'dark',
  },
};

var chart = new ApexCharts(document.querySelector("#visits-conversions"), options);

chart.render();
