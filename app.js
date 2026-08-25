const marketData = [
  {
    id: 1,
    league: 'NFL',
    status: 'Live',
    time: '4th Q • 06:14',
    teams: [
      { name: 'Chiefs', short: 'KC', color: 'red' },
      { name: 'Bills', short: 'BUF', color: 'blue' }
    ],
    odds: [
      { label: 'Chiefs', value: 1.85 },
      { label: 'Bills', value: 2.08 },
      { label: 'Draw', value: 3.10 }
    ]
  },
  {
    id: 2,
    league: 'NBA',
    status: 'Live',
    time: 'Final Q • 2:18',
    teams: [
      { name: 'Lakers', short: 'LAL', color: 'purple' },
      { name: 'Mavericks', short: 'DAL', color: 'gold' }
    ],
    odds: [
      { label: 'Lakers', value: 1.90 },
      { label: 'Mavericks', value: 1.98 },
      { label: 'Over 214.5', value: 1.76 }
    ]
  },
  {
    id: 3,
    league: 'Premier League',
    status: 'Upcoming',
    time: 'Today • 20:45',
    teams: [
      { name: 'Arsenal', short: 'ARS', color: 'red' },
      { name: 'Chelsea', short: 'CHE', color: 'blue' }
    ],
    odds: [
      { label: 'Arsenal', value: 1.68 },
      { label: 'Chelsea', value: 2.45 },
      { label: 'Both teams score', value: 1.84 }
    ]
  },
  {
    id: 4,
    league: 'MLB',
    status: 'Upcoming',
    time: 'Tonight • 21:05',
    teams: [
      { name: 'Yankees', short: 'NYY', color: 'blue' },
      { name: 'Red Sox', short: 'BOS', color: 'red' }
    ],
    odds: [
      { label: 'Yankees', value: 1.72 },
      { label: 'Red Sox', value: 2.20 },
      { label: 'Over 8.5', value: 1.92 }
    ]
  }
];

const state = {
  bankroll: 1840,
  selected: [],
  stake: 25
};

const marketsGrid = document.querySelector('#marketsGrid');
const betSlip = document.querySelector('#betSlip');
const stakeInput = document.querySelector('#stakeInput');
const potentialWin = document.querySelector('#potentialWin');
const bankrollValue = document.querySelector('#bankrollValue');
const selectionCount = document.querySelector('#selectionCount');
const placeBetBtn = document.querySelector('#placeBetBtn');

function renderMarkets() {
  marketsGrid.innerHTML = marketData
    .map(
      (market) => `
        <article class="market-card">
          <div class="market-head">
            <div>
              <p class="market-meta">${market.league}</p>
              <h3>${market.teams[0].name} vs ${market.teams[1].name}</h3>
            </div>
            <span class="tag ${market.status === 'Live' ? 'live' : 'upcoming'}">${market.status}</span>
          </div>

          <div class="market-meta">${market.time}</div>

          <div class="matchup">
            ${market.teams
              .map(
                (team) => `
                  <div class="team-row">
                    <div class="team-name">
                      <span class="team-badge ${team.color}">${team.short}</span>
                      <span>${team.name}</span>
                    </div>
                  </div>
                `
              )
              .join('')}
          </div>

          <div class="market-odds">
            ${market.odds
              .map(
                (option) => `
                  <button class="odds-btn ${state.selected.some((bet) => bet.id === market.id && bet.option === option.label) ? 'selected' : ''}" data-market-id="${market.id}" data-option="${option.label}" data-odds="${option.value}">
                    <strong>${option.value.toFixed(2)}</strong>
                    <span>${option.label}</span>
                  </button>
                `
              )
              .join('')}
          </div>
        </article>
      `
    )
    .join('');

  document.querySelectorAll('.odds-btn').forEach((button) => {
    button.addEventListener('click', () => {
      const marketId = Number(button.dataset.marketId);
      const option = button.dataset.option;
      const odds = Number(button.dataset.odds);

      const existingIndex = state.selected.findIndex((bet) => bet.id === marketId && bet.option === option);

      if (existingIndex >= 0) {
        state.selected.splice(existingIndex, 1);
      } else {
        const market = marketData.find((item) => item.id === marketId);
        const team = market.teams.find((teamItem) => teamItem.name === option) || null;

        state.selected.push({
          id: marketId,
          option,
          odds,
          matchup: `${market.teams[0].name} vs ${market.teams[1].name}`,
          teamName: team ? team.name : option
        });
      }

      renderMarkets();
      renderBetSlip();
    });
  });
}

function renderBetSlip() {
  if (!state.selected.length) {
    betSlip.innerHTML = `
      <div class="empty-state">
        <p>Select a market to start your ticket.</p>
      </div>
    `;
    selectionCount.textContent = '0';
    potentialWin.textContent = '$0.00';
    return;
  }

  betSlip.innerHTML = state.selected
    .map(
      (bet) => `
        <div class="bet-item">
          <div class="bet-item-top">
            <span>${bet.matchup}</span>
            <span>${bet.odds.toFixed(2)}</span>
          </div>
          <strong>${bet.option}</strong>
          <button data-remove-id="${bet.id}" data-remove-option="${bet.option}">Remove</button>
        </div>
      `
    )
    .join('');

  selectionCount.textContent = String(state.selected.length);

  const totalPotential = state.selected.reduce((sum, bet) => sum + state.stake * bet.odds, 0);
  potentialWin.textContent = `$${totalPotential.toFixed(2)}`;

  betSlip.querySelectorAll('button[data-remove-id]').forEach((button) => {
    button.addEventListener('click', () => {
      const id = Number(button.dataset.removeId);
      const option = button.dataset.removeOption;
      state.selected = state.selected.filter((bet) => !(bet.id === id && bet.option === option));
      renderMarkets();
      renderBetSlip();
    });
  });
}

stakeInput.addEventListener('input', (event) => {
  state.stake = Math.max(5, Number(event.target.value) || 5);
  renderBetSlip();
});

placeBetBtn.addEventListener('click', () => {
  if (!state.selected.length) {
    potentialWin.textContent = '$0.00';
    return;
  }

  const totalPotential = state.selected.reduce((sum, bet) => sum + state.stake * bet.odds, 0);
  state.bankroll += totalPotential - state.stake;
  bankrollValue.textContent = `$${state.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  state.selected = [];
  renderMarkets();
  renderBetSlip();
  stakeInput.value = String(state.stake);
});

bankrollValue.textContent = `$${state.bankroll.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
renderMarkets();
renderBetSlip();
