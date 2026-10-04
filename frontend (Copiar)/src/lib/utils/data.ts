export const createDateSeries = ({ count, min, max, value }: { count: number; min: number; max: number; value: string }) => {
  const data = [];
  for (let i = 0; i < count; i++) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    const valor = Math.floor(Math.random() * (max - min + 1)) + min;
    data.push({ date, valor });
  }
  return data;
};
