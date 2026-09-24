// Mobile nav toggle
const burger = document.getElementById('burger');
const navLinks = document.getElementById('navLinks');

burger.addEventListener('click', () => {
  navLinks.classList.toggle('open');
});

navLinks.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => navLinks.classList.remove('open'));
});

// Navbar background on scroll
const navbar = document.getElementById('navbar');
window.addEventListener('scroll', () => {
  navbar.style.borderBottomColor = window.scrollY > 40
    ? 'rgba(247,244,238,0.18)'
    : 'rgba(247,244,238,0.12)';
});

// Lightweight scroll reveal (IntersectionObserver, transform/opacity only)
const revealEls = document.querySelectorAll('.reveal');
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (prefersReducedMotion || !('IntersectionObserver' in window)) {
  revealEls.forEach(el => el.classList.add('in-view'));
} else {
  let delay = 0;
  const groups = new Map();

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const parent = el.parentElement;
        let index = groups.get(parent) || 0;
        el.style.transitionDelay = `${Math.min(index * 60, 240)}ms`;
        groups.set(parent, index + 1);
        el.classList.add('in-view');
        observer.unobserve(el);
      }
    });
  }, { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });

  revealEls.forEach(el => observer.observe(el));
}

// Booking form (demo only — no backend)
const bookingForm = document.getElementById('bookingForm');
const formNote = document.getElementById('formNote');

bookingForm.addEventListener('submit', (e) => {
  e.preventDefault();
  formNote.textContent = 'Grazie! Ti risponderemo entro 24 ore. (form demo, non collegato a un backend)';
  bookingForm.reset();
});
