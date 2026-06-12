/**
 * Anmol Labs Homepage — Interaction Script
 * Handles: scroll nav, stacked card parallax, mobile menu
 */

(function () {
  'use strict';

  /* ── Navbar scroll state ────────────────────────────────── */
  const nav = document.getElementById('mainNav');

  function updateNav() {
    if (window.scrollY > 40) {
      nav.classList.add('scrolled');
    } else {
      nav.classList.remove('scrolled');
    }
  }

  window.addEventListener('scroll', updateNav, { passive: true });
  updateNav();

  /* ── Active nav link on scroll ──────────────────────────── */
  const sections = document.querySelectorAll('section[id]');
  const navLinks = document.querySelectorAll('.nav-links a');

  const sectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          navLinks.forEach((link) => {
            link.classList.remove('active');
            if (link.getAttribute('href') === '#' + entry.target.id) {
              link.classList.add('active');
            }
          });
        }
      });
    },
    { threshold: 0.35 }
  );

  sections.forEach((section) => sectionObserver.observe(section));

  /* ── Card Slide-Up Popup Animation ──────────────────────── */
  const cards = document.querySelectorAll('.project-card');

  const cardObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        // Optional: stop observing once it's visible if you only want it to animate once
        // cardObserver.unobserve(entry.target);
      } else {
        // Remove class to animate again when scrolling back up
        entry.target.classList.remove('is-visible');
      }
    });
  }, {
    threshold: 0.15,
    rootMargin: '0px 0px -50px 0px'
  });

  cards.forEach((card) => {
    cardObserver.observe(card);
  });

  /* ── Smooth hero CTA scroll ────────────────────────────── */
  const heroExploreBtn = document.getElementById('heroExploreBtn');
  if (heroExploreBtn) {
    heroExploreBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.getElementById('creations');
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  }

  /* ── Launch Gini ───────────────────────────────────────── */
  const launchGiniBtn = document.getElementById('launchGiniBtn');
  if (launchGiniBtn) {
    launchGiniBtn.addEventListener('click', (e) => {
      // Navigate to the main app
      // href="index.html" already handles this, but we can add a transition
      document.body.style.opacity = '0';
      document.body.style.transition = 'opacity 0.3s ease';
    });
  }

  /* ── Mobile menu toggle ────────────────────────────────── */
  const mobileToggle = document.getElementById('mobileToggle');
  const navLinksList = document.querySelector('.nav-links');
  let menuOpen = false;

  if (mobileToggle) {
    mobileToggle.addEventListener('click', () => {
      menuOpen = !menuOpen;
      mobileToggle.setAttribute('aria-expanded', menuOpen);

      if (menuOpen) {
        // Create and show mobile menu overlay
        let overlay = document.getElementById('mobileMenuOverlay');
        if (!overlay) {
          overlay = createMobileMenu();
        }
        overlay.style.display = 'flex';
        requestAnimationFrame(() => {
          overlay.style.opacity = '1';
          overlay.style.transform = 'translateY(0)';
        });
        mobileToggle.children[0].style.transform = 'rotate(45deg) translate(5px, 5px)';
        mobileToggle.children[1].style.opacity = '0';
        mobileToggle.children[2].style.transform = 'rotate(-45deg) translate(5px, -5px)';
      } else {
        closeMobileMenu();
      }
    });
  }

  function createMobileMenu() {
    const overlay = document.createElement('div');
    overlay.id = 'mobileMenuOverlay';
    overlay.style.cssText = `
      position: fixed;
      top: 64px;
      left: 0;
      right: 0;
      background: rgba(235, 243, 252, 0.97);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid rgba(180, 200, 230, 0.3);
      padding: 24px 32px;
      display: flex;
      flex-direction: column;
      gap: 4px;
      z-index: 999;
      opacity: 0;
      transform: translateY(-8px);
      transition: opacity 0.25s ease, transform 0.25s ease;
    `;

    const links = [
      { href: '#', label: 'Home' },
      { href: '#creations', label: 'Creations' },
      { href: '#about', label: 'About' },
      { href: '#labs', label: 'Labs' },
      { href: '#contact', label: 'Contact' },
    ];

    links.forEach((linkData) => {
      const a = document.createElement('a');
      a.href = linkData.href;
      a.textContent = linkData.label;
      a.style.cssText = `
        display: block;
        padding: 14px 0;
        font-size: 18px;
        font-weight: 600;
        color: #1a1a2e;
        text-decoration: none;
        border-bottom: 1px solid rgba(180, 200, 230, 0.2);
        font-family: 'Inter', sans-serif;
        transition: color 0.2s;
      `;
      a.addEventListener('click', () => {
        menuOpen = false;
        closeMobileMenu();
      });
      overlay.appendChild(a);
    });

    document.body.appendChild(overlay);
    return overlay;
  }

  function closeMobileMenu() {
    const overlay = document.getElementById('mobileMenuOverlay');
    if (overlay) {
      overlay.style.opacity = '0';
      overlay.style.transform = 'translateY(-8px)';
      setTimeout(() => { overlay.style.display = 'none'; }, 250);
    }
    if (mobileToggle) {
      mobileToggle.children[0].style.transform = '';
      mobileToggle.children[1].style.opacity = '';
      mobileToggle.children[2].style.transform = '';
    }
  }

  /* ── Card hover micro-lift ─────────────────────────────── */
  cards.forEach((card) => {
    card.addEventListener('mouseenter', () => {
      // Only lift if not being stacked-out
      const rect = card.getBoundingClientRect();
      if (rect.top >= 80) {
        card.style.boxShadow = '0 20px 64px rgba(80, 100, 160, 0.18)';
      }
    });
    card.addEventListener('mouseleave', () => {
      card.style.boxShadow = '';
    });
  });

  /* ── Orb subtle parallax with mouse ───────────────────── */
  const heroOrb = document.querySelector('.hero-orb');
  if (heroOrb) {
    document.addEventListener('mousemove', (e) => {
      const xRatio = (e.clientX / window.innerWidth - 0.5) * 2;
      const yRatio = (e.clientY / window.innerHeight - 0.5) * 2;
      heroOrb.style.transform = `translate(${xRatio * 8}px, ${yRatio * 8}px)`;
    }, { passive: true });
  }

  /* ── Page fade in ──────────────────────────────────────── */
  document.body.style.opacity = '0';
  document.body.style.transition = 'opacity 0.4s ease';
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      document.body.style.opacity = '1';
    });
  });

  /* ── Search placeholder ─────────────────────────────────── */
  const searchBtn = document.getElementById('searchBtn');
  if (searchBtn) {
    searchBtn.addEventListener('click', () => {
      // Placeholder — connect to real search later
      alert('Search coming soon!');
    });
  }

  /* ── Sign In placeholder ────────────────────────────────── */
  const signinBtn = document.getElementById('signinBtn');
  if (signinBtn) {
    signinBtn.addEventListener('click', () => {
      alert('Authentication coming soon!');
    });
  }

})();
