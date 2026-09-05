export type DataColumn<Row> = {
  key: string;
  heading: string;
  render: (row: Row) => React.ReactNode;
};

export function DataTable<Row>({
  caption,
  columns,
  rows,
  rowKey,
  emptyMessage = "Nothing to show yet.",
}: {
  caption: string;
  columns: DataColumn<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  emptyMessage?: string;
}) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={`${caption}, scrollable table`}>
      <table className="data-table">
        <caption>{caption}</caption>
        <thead><tr>{columns.map((column) => <th scope="col" key={column.key}>{column.heading}</th>)}</tr></thead>
        <tbody>
          {rows.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td data-label={column.heading} key={column.key}>{column.render(row)}</td>)}</tr>)}
          {!rows.length && <tr><td colSpan={columns.length} className="table-empty">{emptyMessage}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
