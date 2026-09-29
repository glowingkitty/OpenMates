const classResults = {
  provider: 'Urban Sports Club',
  results: [{
    id: 'request-1',
    result_count: 2,
    results: [
      { name: 'Yoga Flow', date: '2026-10-01', time_range: '18:00–19:00', venue_name: 'Studio One', venue_city: 'Berlin', spots_display: '4 spots left' },
      { name: 'Strength Circuit', date: '2026-10-02', time_range: '17:00–18:00', venue_name: 'Studio Two', venue_city: 'Berlin', spots_display: '6 spots left' },
    ],
  }],
};

const defaultProps = { value: classResults, appId: 'fitness', path: 'fitness-test' };

export default defaultProps;
export const variants = { empty: { ...defaultProps, value: { provider: 'Urban Sports Club', results: [] } } };
