// Auto-add loading state untuk semua form submissions
document.addEventListener('DOMContentLoaded', function() {
  // Form loading state
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function(e) {
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn && !form.classList.contains('loading')) {
        form.classList.add('loading');
        submitBtn.classList.add('loading');
        submitBtn.disabled = true;
      }
    });
  });

  // Button loading state untuk delete/action buttons
  document.querySelectorAll('[data-loading-action]').forEach(btn => {
    btn.addEventListener('click', function() {
      if (!this.classList.contains('loading')) {
        this.classList.add('loading');
        this.disabled = true;
      }
    });
  });
});
