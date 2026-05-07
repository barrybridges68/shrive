document.addEventListener("DOMContentLoaded", function () {
  const calendarEl = document.getElementById("dayGrid");

  // Theme colors
  const colors = {
    blue: "#338dd7",
    cyan: "#35c2fe",
    orange: "#ff9446",
    green: "#26c77b",
    yellow: "#f3c83a",
    purple: "#8067dc",
    red: "#ff5a5a"
  };

  // Get current date
  const currentDate = new Date();

  const calendar = new FullCalendar.Calendar(calendarEl, {
    headerToolbar: {
      left: "prev,next today",
      center: "title",
      right: "dayGridMonth,dayGridWeek,dayGridDay"
    },
    initialDate: currentDate, // Use current date
    initialView: 'dayGridMonth',
    navLinks: true,
    editable: true,
    dayMaxEvents: true,
    height: 'auto',
    themeSystem: 'bootstrap5',
    buttonText: {
      today: 'Today',
      month: 'Month',
      week: 'Week',
      day: 'Day'
    },
    events: [
      { title: "All Day Event", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 1), color: colors.orange },
      { title: "Long Event", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 7), end: new Date(currentDate.getFullYear(), currentDate.getMonth(), 10), color: colors.blue },
      { groupId: 999, title: "Birthday", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 9, 16, 0), color: colors.cyan },
      { groupId: 999, title: "Birthday", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 16, 16, 0), color: colors.yellow },
      { title: "Conference", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 11), end: new Date(currentDate.getFullYear(), currentDate.getMonth(), 13), color: colors.orange },
      { title: "Meeting", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 14, 10, 30), end: new Date(currentDate.getFullYear(), currentDate.getMonth(), 14, 12, 30), color: colors.purple },
      { title: "Lunch", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 16, 12, 0), color: colors.green },
      { title: "Meeting", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 18, 14, 30), color: colors.cyan },
      { title: "Interview", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 21, 17, 30), color: colors.yellow },
      { title: "Meeting", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 22, 20, 0), color: colors.blue },
      { title: "Birthday", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 13, 7, 0), color: colors.green },
      { title: "Click for Google", url: "http://google.com/", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 28), color: colors.cyan },
      { title: "Interview", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 20), color: colors.green },
      { title: "Product Launch", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 29), color: colors.green },
      { title: "Leave", start: new Date(currentDate.getFullYear(), currentDate.getMonth(), 25), color: colors.yellow },
    ],
    // Modern styling
    eventTimeFormat: {
      hour: '2-digit',
      minute: '2-digit',
      meridiem: false
    },
    eventDidMount: function (info) {
      // Add hover effect
      info.el.style.transition = 'transform 0.2s, box-shadow 0.2s';
      info.el.addEventListener('mouseover', function () {
        info.el.style.transform = 'scale(1.02)';
        info.el.style.boxShadow = '0 5px 15px rgba(0,0,0,0.1)';
        info.el.style.zIndex = '999';
      });
      info.el.addEventListener('mouseout', function () {
        info.el.style.transform = 'scale(1)';
        info.el.style.boxShadow = 'none';
        info.el.style.zIndex = '';
      });
    }
  });

  calendar.render();
});
