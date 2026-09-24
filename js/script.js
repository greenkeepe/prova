// Mobile nav toggle
const burger = document.getElementById('burger');
const navLinks = document.getElementById('navLinks');

burger.addEventListener('click', () => {
  navLinks.classList.toggle('open');
});

navLinks.querySelectorAll('a').forEach(link => {
  link.addEventListener('click', () => navLinks.classList.remove('open'));
});

// Navbar shrink on scroll
const navbar = document.getElementById('navbar');
window.addEventListener('scroll', () => {
  navbar.style.padding = window.scrollY > 40 ? '12px 6%' : '20px 6%';
});

// Booking form (demo only — no backend, just visual feedback)
const bookingForm = document.getElementById('bookingForm');
const formNote = document.getElementById('formNote');

bookingForm.addEventListener('submit', (e) => {
  e.preventDefault();
  formNote.textContent = 'Grazie! Ti risponderemo al più presto. (form demo, non collegato a un backend)';
  bookingForm.reset();
});

// Play buttons (demo only)
document.querySelectorAll('.play-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.textContent = btn.textContent === '▶' ? '❚❚' : '▶';
  });
});
