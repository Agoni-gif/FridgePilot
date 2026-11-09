<script setup lang="ts">
defineProps<{
  sideTitle?: string
  sideLead?: string
}>()
</script>

<template>
  <div class="auth-page">
    <div class="auth-frame">
      <div class="brand">
        <img class="logo" src="/logo-mark.svg" alt="" width="40" height="40" />
        <span class="name">FridgePilot</span>
      </div>

      <div class="auth-stage">
        <div class="auth-main">
          <slot />
        </div>

        <aside v-if="sideTitle || sideLead" class="auth-side" aria-hidden="true">
          <div class="side-mark">
            <img src="/logo-mark.svg" alt="" width="72" height="72" />
          </div>
          <p v-if="sideTitle" class="side-title">{{ sideTitle }}</p>
          <p v-if="sideLead" class="side-lead">{{ sideLead }}</p>
        </aside>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: clamp(1.5rem, 5vw, 3rem);
  background: #fff;
}

.auth-frame {
  width: min(100%, 380px);
  animation: auth-rise 480ms var(--ease) both;
}

.brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  margin-bottom: 2.35rem;
}

.logo {
  width: 2.2rem;
  height: 2.2rem;
  display: block;
  border-radius: 50%;
  flex-shrink: 0;
}

.name {
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: -0.045em;
  color: var(--brand);
  line-height: 1;
}

.auth-stage {
  display: grid;
}

.auth-side {
  display: none;
}

@media (min-width: 960px) {
  .auth-frame {
    width: min(100%, 720px);
  }

  .brand {
    margin-bottom: 2.6rem;
  }

  .auth-stage {
    grid-template-columns: minmax(0, 360px) 280px;
    justify-content: center;
    align-items: stretch;
    gap: 2.75rem;
  }

  .auth-side {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    padding: 2rem 1.4rem;
    border-radius: 16px;
    background: #f5f6f8;
  }

  .side-mark {
    width: 4.75rem;
    height: 4.75rem;
    border-radius: 50%;
    display: grid;
    place-items: center;
    background: #fff;
    margin-bottom: 1.1rem;
  }

  .side-mark img {
    width: 2.85rem;
    height: 2.85rem;
    display: block;
  }

  .side-title {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: -0.02em;
    color: var(--ink);
  }

  .side-lead {
    margin: 0.45rem 0 0;
    max-width: 14.5rem;
    font-size: 0.82rem;
    line-height: 1.55;
    color: var(--muted);
  }
}

@keyframes auth-rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
