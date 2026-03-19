/* ══════════════════════════════════════════════════════
   REYART — Fuar Tasarım & İç Mimarlık
   script.js
══════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /* ─── GSAP Registration ────────────────────────────── */
  if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);
  }

  /* ─── Custom Cursor ────────────────────────────────── */
  const cursor = document.getElementById('cursor');
  const cursorFollower = document.getElementById('cursorFollower');

  let mouseX = 0, mouseY = 0;
  let followerX = 0, followerY = 0;
  let animFrame;

  document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
    if (cursor) {
      cursor.style.left = mouseX + 'px';
      cursor.style.top  = mouseY + 'px';
    }
  });

  function animateCursorFollower() {
    if (cursorFollower) {
      followerX += (mouseX - followerX) * 0.12;
      followerY += (mouseY - followerY) * 0.12;
      cursorFollower.style.left = followerX + 'px';
      cursorFollower.style.top  = followerY + 'px';
    }
    animFrame = requestAnimationFrame(animateCursorFollower);
  }
  animateCursorFollower();

  /* Hide cursor on mobile */
  if ('ontouchstart' in window) {
    if (cursor) cursor.style.display = 'none';
    if (cursorFollower) cursorFollower.style.display = 'none';
  }

  /* ─── Navbar: Scroll Behavior ──────────────────────── */
  const navbar = document.getElementById('navbar');

  function handleNavbarScroll() {
    if (window.scrollY > 60) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  }

  window.addEventListener('scroll', handleNavbarScroll, { passive: true });

  /* ─── Mobile Menu ──────────────────────────────────── */
  const hamburger = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobileMenu');
  const mobileLinks = document.querySelectorAll('.mobile-link');

  function closeMobileMenu() {
    hamburger.classList.remove('open');
    mobileMenu.classList.remove('open');
    document.body.style.overflow = '';
  }

  hamburger.addEventListener('click', () => {
    const isOpen = mobileMenu.classList.contains('open');
    if (isOpen) {
      closeMobileMenu();
    } else {
      hamburger.classList.add('open');
      mobileMenu.classList.add('open');
      document.body.style.overflow = 'hidden';
    }
  });

  mobileLinks.forEach(link => link.addEventListener('click', closeMobileMenu));

  /* ─── Smooth Scroll for Anchor Links ──────────────── */
  document.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener('click', function (e) {
      const targetId = this.getAttribute('href');
      const target = document.querySelector(targetId);
      if (!target) return;
      e.preventDefault();
      const navH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nav-h')) || 80;
      const top = target.getBoundingClientRect().top + window.scrollY - navH;
      window.scrollTo({ top, behavior: 'smooth' });
    });
  });

  /* ─── Hero Entrance Animation ──────────────────────── */
  function initHeroAnimation() {
    if (typeof gsap === 'undefined') {
      // Fallback: just show elements
      document.querySelectorAll('[data-gsap="hero"]').forEach(el => {
        el.style.opacity = '1';
      });
      return;
    }

    const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });

    const overline  = document.querySelector('.hero-overline');
    const lines     = document.querySelectorAll('.hero-line');
    const heroBody  = document.querySelector('.hero-body');
    const actions   = document.querySelector('.hero-actions');
    const scrollInd = document.querySelector('.hero-scroll');
    const badge     = document.querySelector('.hero-badge');

    // Set initial states
    if (overline)  gsap.set(overline,  { opacity: 0, y: 20 });
    if (heroBody)  gsap.set(heroBody,  { opacity: 0, y: 20 });
    if (actions)   gsap.set(actions,   { opacity: 0, y: 15 });
    if (scrollInd) gsap.set(scrollInd, { opacity: 0 });
    if (badge)     gsap.set(badge,     { opacity: 0, x: 20 });

    lines.forEach(line => {
      gsap.set(line, { clipPath: 'inset(0 100% 0 0)', opacity: 1 });
    });

    tl
      .to(overline, { opacity: 1, y: 0, duration: 0.7 }, 0.2)
      .to(lines, {
        clipPath: 'inset(0 0% 0 0)',
        duration: 0.9,
        stagger: 0.12,
        ease: 'power4.out'
      }, 0.5)
      .to(heroBody, { opacity: 1, y: 0, duration: 0.7 }, 0.95)
      .to(actions, { opacity: 1, y: 0, duration: 0.6 }, 1.15)
      .to(scrollInd, { opacity: 1, duration: 0.6 }, 1.35)
      .to(badge, { opacity: 1, x: 0, duration: 0.7 }, 1.4);
  }

  /* ─── ScrollTrigger Animations ─────────────────────── */
  function initScrollAnimations() {
    if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') {
      // Fallback: show all gsap-animated elements
      document.querySelectorAll('[data-gsap]').forEach(el => {
        el.style.opacity = '1';
        el.style.transform = 'none';
      });
      return;
    }

    /* fade-up */
    gsap.utils.toArray('[data-gsap="fade-up"]').forEach(el => {
      gsap.set(el, { opacity: 0, y: 50 });
      ScrollTrigger.create({
        trigger: el,
        start: 'top 85%',
        onEnter: () => gsap.to(el, { opacity: 1, y: 0, duration: 0.85, ease: 'power3.out' })
      });
    });

    /* fade-right (slide from left) */
    gsap.utils.toArray('[data-gsap="fade-right"]').forEach(el => {
      gsap.set(el, { opacity: 0, x: -60 });
      ScrollTrigger.create({
        trigger: el,
        start: 'top 80%',
        onEnter: () => gsap.to(el, { opacity: 1, x: 0, duration: 0.95, ease: 'power3.out' })
      });
    });

    /* fade-left (slide from right) */
    gsap.utils.toArray('[data-gsap="fade-left"]').forEach(el => {
      gsap.set(el, { opacity: 0, x: 60 });
      ScrollTrigger.create({
        trigger: el,
        start: 'top 80%',
        onEnter: () => gsap.to(el, { opacity: 1, x: 0, duration: 0.95, ease: 'power3.out' })
      });
    });

    /* stagger groups — animate children when parent enters view */
    const staggerGroups = {};

    document.querySelectorAll('[data-gsap="stagger"]').forEach(el => {
      const parent = el.parentElement;
      if (!staggerGroups[parent]) staggerGroups[parent] = [];
      staggerGroups[parent].push(el);
    });

    Object.values(staggerGroups).forEach(group => {
      gsap.set(group, { opacity: 0, y: 35 });
      ScrollTrigger.create({
        trigger: group[0].parentElement,
        start: 'top 82%',
        onEnter: () =>
          gsap.to(group, {
            opacity: 1,
            y: 0,
            duration: 0.75,
            stagger: 0.12,
            ease: 'power3.out'
          })
      });
    });
  }

  /* ─── CountUp Animation ─────────────────────────────── */
  function countUp(el) {
    const target = parseInt(el.dataset.count, 10);
    const duration = 1800;
    const start = performance.now();

    function update(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(eased * target);
      if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
  }

  function initCounters() {
    const counters = document.querySelectorAll('[data-count]');
    if (!counters.length) return;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && !entry.target.dataset.counted) {
          entry.target.dataset.counted = 'true';
          countUp(entry.target);
        }
      });
    }, { threshold: 0.5 });

    counters.forEach(c => observer.observe(c));
  }

  /* ─── Process Step Line Reveal ──────────────────────── */
  function initProcessReveal() {
    const steps = document.querySelectorAll('.process-step');
    if (!steps.length) return;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-in');
        }
      });
    }, { threshold: 0.3 });

    steps.forEach(step => observer.observe(step));
  }

  /* ─── Portfolio Filter ──────────────────────────────── */
  function initPortfolioFilter() {
    const filterBtns = document.querySelectorAll('.filter-btn');
    const projectCards = document.querySelectorAll('.project-card');

    if (!filterBtns.length || !projectCards.length) return;

    filterBtns.forEach(btn => {
      btn.addEventListener('click', function () {
        const filter = this.dataset.filter;

        // Update active button
        filterBtns.forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        // Filter cards
        projectCards.forEach(card => {
          const cat = card.dataset.category;
          const show = filter === 'all' || cat === filter;

          if (show) {
            card.style.opacity = '0';
            card.style.display = 'block';
            setTimeout(() => {
              card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
              card.style.transform = 'scale(1) translateY(0)';
              card.style.opacity = '1';
            }, 20);
          } else {
            card.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.96) translateY(8px)';
            setTimeout(() => { card.style.display = 'none'; }, 350);
          }
        });
      });
    });
  }

  /* ─── Form Submit Handler ───────────────────────────── */
  function initContactForm() {
    const form = document.getElementById('contactForm');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      const btn = this.querySelector('button[type="submit"]');
      const originalText = btn.textContent;
      btn.textContent = 'Gönderiliyor...';
      btn.disabled = true;

      // Simulate async
      setTimeout(() => {
        btn.textContent = '✓ Talebiniz Alındı';
        btn.style.background = '#2d6a4f';
        form.reset();
        setTimeout(() => {
          btn.textContent = originalText;
          btn.style.background = '';
          btn.disabled = false;
        }, 4000);
      }, 1200);
    });
  }

  /* ─── Parallax: Hero Glow ───────────────────────────── */
  function initParallax() {
    const glow = document.querySelector('.hero-bg-glow');
    if (!glow) return;

    window.addEventListener('scroll', () => {
      const scrollY = window.scrollY;
      glow.style.transform = `translateY(${scrollY * 0.15}px)`;
    }, { passive: true });
  }

  /* ─── Navbar Active Link on Scroll ─────────────────── */
  function initActiveNavLink() {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-links a[href^="#"]');

    if (!sections.length || !navLinks.length) return;

    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          navLinks.forEach(link => {
            link.style.color = link.getAttribute('href') === '#' + id
              ? 'var(--gold)'
              : '';
          });
        }
      });
    }, { rootMargin: '-40% 0px -55% 0px' });

    sections.forEach(section => observer.observe(section));
  }

  /* ─── Reveal on Load (no GSAP fallback) ────────────── */
  function initFallbackReveal() {
    if (typeof gsap !== 'undefined') return;

    const style = document.createElement('style');
    style.textContent = `
      [data-gsap] { opacity: 1 !important; transform: none !important; }
      .hero-overline, .hero-body, .hero-actions, .hero-scroll { opacity: 1 !important; }
      .hero-line { clip-path: none !important; }
      .hero-badge { opacity: 1 !important; }
    `;
    document.head.appendChild(style);
  }

  /* ─── Hover Magnetic Effect on Buttons ─────────────── */
  function initMagneticButtons() {
    document.querySelectorAll('.btn').forEach(btn => {
      btn.addEventListener('mousemove', function (e) {
        const rect = this.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dx = (e.clientX - cx) * 0.18;
        const dy = (e.clientY - cy) * 0.18;
        this.style.transform = `translate(${dx}px, ${dy}px)`;
      });
      btn.addEventListener('mouseleave', function () {
        this.style.transition = 'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        this.style.transform = '';
        setTimeout(() => { this.style.transition = ''; }, 500);
      });
    });
  }

  /* ─── Init All ──────────────────────────────────────── */
  function init() {
    initFallbackReveal();
    initHeroAnimation();
    initScrollAnimations();
    initCounters();
    initProcessReveal();
    initPortfolioFilter();
    initContactForm();
    initParallax();
    initActiveNavLink();
    initMagneticButtons();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
