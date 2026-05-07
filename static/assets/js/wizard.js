document.addEventListener('DOMContentLoaded', function () {
  // Cache DOM elements
  const tabButtons = document.querySelectorAll('.wizard-steps .nav-link');
  const progressBar = document.getElementById('wizard-progress');
  const nextButtons = document.querySelectorAll('.next-step');
  const prevButtons = document.querySelectorAll('.prev-step');

  // Initialize wizard
  function updateWizardState(activeIndex) {
    // Update progress bar
    const progressPercent = (activeIndex + 1) * 25;
    progressBar.style.width = progressPercent + '%';
    progressBar.setAttribute('aria-valuenow', progressPercent);

    // Reset all step icons to default state
    tabButtons.forEach(btn => {
      const icon = btn.querySelector('.wizard-step-icon');
      const iconText = btn.querySelector('.wizard-step-icon i');
      icon.className = 'wizard-step-icon bg-light rounded-circle p-3 mb-2 shadow-sm';
      iconText.classList.remove('text-primary', 'text-success');
    });

    // Mark current step as active
    const currentIcon = tabButtons[activeIndex].querySelector('.wizard-step-icon');
    const currentIconText = tabButtons[activeIndex].querySelector('.wizard-step-icon i');
    currentIcon.className = 'wizard-step-icon bg-primary-subtle rounded-circle p-3 mb-2 shadow-sm';
    currentIconText.classList.add('text-primary');

    // Mark completed steps
    for (let i = 0; i < activeIndex; i++) {
      const completedButton = tabButtons[i];
      completedButton.classList.add('completed');
      const completedIcon = completedButton.querySelector('.wizard-step-icon');
      const completedIconText = completedButton.querySelector('.wizard-step-icon i');
      completedIcon.className = 'wizard-step-icon bg-success-subtle rounded-circle p-3 mb-2 shadow-sm';
      completedIconText.classList.add('text-success');
    }
  }

  // Setup event listeners for Bootstrap tabs
  tabButtons.forEach((button, index) => {
    button.addEventListener('shown.bs.tab', () => updateWizardState(index));
  });

  // Navigation between steps with next/prev buttons
  nextButtons.forEach(button => {
    button.addEventListener('click', () => {
      const activeTab = document.querySelector('.wizard-steps .nav-link.active');
      const activeIndex = Array.from(tabButtons).indexOf(activeTab);
      const nextIndex = activeIndex + 1;

      if (nextIndex < tabButtons.length) {
        // Use Bootstrap's tab API to show the next tab
        const nextTab = new bootstrap.Tab(tabButtons[nextIndex]);
        nextTab.show();
      }
    });
  });

  prevButtons.forEach(button => {
    button.addEventListener('click', () => {
      const activeTab = document.querySelector('.wizard-steps .nav-link.active');
      const activeIndex = Array.from(tabButtons).indexOf(activeTab);
      const prevIndex = activeIndex - 1;

      if (prevIndex >= 0) {
        // Use Bootstrap's tab API to show the previous tab
        const prevTab = new bootstrap.Tab(tabButtons[prevIndex]);
        prevTab.show();
      }
    });
  });

  // Custom pricing calculations for the food order
  const priceElements = {
    basePrice: 12.99,
    sizeUpgrade: 2.00,
    toppings: {
      avocado: 1.50,
      cheese: 1.00,
      bacon: 1.25
    }
  };

  // Size selection handlers
  const sizeRadios = document.querySelectorAll('input[name="size"]');
  sizeRadios.forEach(radio => {
    radio.addEventListener('change', updateTotalPrice);
  });

  // Topping selection handlers
  const toppingCheckboxes = document.querySelectorAll('input[id^="topping-"]');
  toppingCheckboxes.forEach(checkbox => {
    checkbox.addEventListener('change', updateTotalPrice);
  });

  function updateTotalPrice() {
    let total = priceElements.basePrice;

    // Add size upgrade if large is selected
    if (document.getElementById('size-large').checked) {
      total += priceElements.sizeUpgrade;
    }

    // Add toppings
    if (document.getElementById('topping-avocado').checked) {
      total += priceElements.toppings.avocado;
    }
    if (document.getElementById('topping-cheese').checked) {
      total += priceElements.toppings.cheese;
    }
    if (document.getElementById('topping-bacon').checked) {
      total += priceElements.toppings.bacon;
    }

    // Update display
    document.getElementById('total-price').textContent = '$' + total.toFixed(2);
  }

  // Initialize the wizard state
  updateWizardState(0);
  updateTotalPrice();
});