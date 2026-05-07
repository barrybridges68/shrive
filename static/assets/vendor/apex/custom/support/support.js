document.addEventListener("DOMContentLoaded", function () {
  // Sample data for support tickets
  const supportTicketsData = {
    series: [{
      name: 'Open Tickets',
      data: [10, 15, 14, 20, 18, 25, 30]
    }, {
      name: 'Closed Tickets',
      data: [5, 10, 8, 12, 15, 20, 25]
    }],
    chart: {
      type: 'line',
      height: 350
    },
    stroke: {
      curve: 'smooth'
    },
    xaxis: {
      categories: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    },
    colors: ['#6366f1', '#22c55e'],
    tooltip: {
      theme: 'dark',
      x: {
        format: 'dd MMM'
      }
    }
  };

  // Render the chart
  const chart = new ApexCharts(document.querySelector("#supportTickets"), supportTicketsData);
  chart.render();
});