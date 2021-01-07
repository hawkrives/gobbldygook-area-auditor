use clap::Clap;
use formatter::area_of_study::AreaOfStudy;
use formatter::student::{AreaOfStudy as AreaPointer, Emphasis, Student};
use formatter::to_csv::{CsvOptions, ToCsv};
use itertools::Itertools;
use rusqlite::{named_params, Connection, Error as RusqliteError, OpenFlags, Result};
use serde_path_to_error;
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;

/// This doc string acts as a help message when the user runs '--help'
/// as do all doc strings on fields
#[derive(Clap, Debug)]
#[clap(
    version = "1.0",
    author = "Hawken MacKay Rives <degreepath@hawkrives.fastmail.fm>"
)]
struct Opts {
    /// Sets the database path
    db_path: String,
    /// Which area of study to look up
    area_code: String,
    /// Enables header debugging
    #[clap(long)]
    debug: bool,
    /// Outputs the data as HTML tables
    #[clap(long)]
    as_html: bool,
    /// Outputs the data as a single CSV document
    #[clap(long)]
    as_csv: bool,
}

fn main() {
    let opts: Opts = Opts::parse();

    let results = report_for_area_by_catalog(&opts.db_path, &opts.area_code).unwrap();

    if opts.as_csv {
        print_as_csv(&opts, results);
    } else if opts.as_html {
        print_as_html(&opts, results);
    } else {
        unimplemented!()
    }
}

struct MappedResult {
    header: Vec<String>,
    data: Vec<String>,
    catalog: String,
    stnum: String,
    name: String,
    requirements: Vec<String>,
    emphases: Vec<String>,
    emphasis_req_names: Vec<String>,
}

fn report_for_area_by_catalog<P: AsRef<Path>>(
    db_path: P,
    area_code: &str,
) -> Result<Vec<MappedResult>, RusqliteError> {
    let conn = Connection::open_with_flags(db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;

    let branch = "cond";

    let mut stmt = conn.prepare("
        SELECT b.result, sd.input_data
        FROM branch b
            LEFT JOIN server_data sd on (b.stnum, b.catalog, b.code) = (sd.stnum, sd.catalog, sd.code)
        WHERE b.branch = :branch
            AND b.code = :code
        ORDER BY b.code, b.stnum
    ").unwrap();

    let params = named_params! {":code": area_code, ":branch": branch};

    let options = CsvOptions {};

    let results = stmt
        .query_map_named(params, |row| {
            let result: String = row.get(0).unwrap();
            let student: String = row.get(1).unwrap();

            Ok((student, result))
        })?
        .map(|pair| pair.unwrap())
        .map(|(student, result)| {
            // let value: serde_json::Value = serde_json::from_str(&student).unwrap();
            // let student = serde_json::to_string_pretty(&value).unwrap();

            let student_deserializer = &mut serde_json::Deserializer::from_str(student.as_str());
            let student: Student = match serde_path_to_error::deserialize(student_deserializer) {
                Ok(r) => r,
                Err(err) => {
                    eprintln!("student error");

                    eprintln!("{}", student);
                    dbg!(err);

                    panic!();
                }
            };

            // let value: serde_json::Value = serde_json::from_str(&result).unwrap();
            // let result = serde_json::to_string_pretty(&value).unwrap();

            let result_deserializer = &mut serde_json::Deserializer::from_str(result.as_str());
            let result: AreaOfStudy = match serde_path_to_error::deserialize(result_deserializer) {
                Ok(r) => r,
                Err(err) => {
                    eprintln!("result error");

                    eprintln!("{}", result);
                    eprintln!("{}", err);
                    eprintln!("at {}", err.path());
                    dbg!(student.stnum);

                    panic!();
                }
            };

            // TODO: handle case where student's catalog != area's catalog
            let catalog = student.catalog.clone();
            let stnum = student.stnum.clone();
            let name = student.name.clone();

            let records = result.get_record(&student, &options, false);
            let requirements = result.get_requirements();

            let emphases = student
                .areas
                .iter()
                .filter_map(|a| match a {
                    AreaPointer::Emphasis(Emphasis { name, .. }) => Some(name),
                    _ => None,
                })
                .cloned()
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect::<Vec<_>>();

            let emphasis_req_names = requirements
                .iter()
                .filter(|e| e.starts_with("Emphasis: "))
                .map(|name| String::from(name.split(" → ").take(1).last().unwrap()))
                .collect::<BTreeSet<_>>()
                .into_iter()
                .collect::<Vec<_>>();

            let mut header: Vec<String> = Vec::with_capacity(records.len());
            let mut data: Vec<String> = Vec::with_capacity(records.len());

            for (th, td) in records.into_iter() {
                header.push(th);
                data.push(td);
            }

            MappedResult {
                header,
                data,
                requirements,
                emphases,
                emphasis_req_names,
                catalog,
                stnum,
                name,
            }
        });

    let results: Vec<MappedResult> = {
        let mut r = results.collect::<Vec<_>>();

        r.sort_by_cached_key(|s| {
            (
                s.emphases.join(","),
                s.name.clone(),
                s.stnum.clone(),
            )
        });

        r
    };

    Ok(results)
}

fn print_as_csv(opts: &Opts, results: Vec<MappedResult>) -> () {
    let mut wtr = csv::WriterBuilder::new()
        .has_headers(false)
        .from_writer(std::io::stdout());

    let longest_header = results
        .iter()
        .map(|r: &MappedResult| std::cmp::max(r.header.len(), r.data.len()))
        .max()
        .unwrap();

    let mut last_header: Vec<String> = Vec::new();
    let mut last_requirements: Vec<String> = Vec::new();
    // let mut last_catalog: String = String::from("");

    for (i, pair) in results.into_iter().enumerate() {
        let MappedResult {
            mut header,
            mut data,
            requirements,
            catalog,
            emphasis_req_names,
            emphases: _,
            stnum: _,
            name: _,
        } = pair;

        // make sure that we have enough columns
        header.resize(longest_header, String::from(""));

        if opts.debug && last_header != header {
            // write out a blank line, then a line with the new catalog year
            let blank = vec![""; longest_header];
            wtr.write_record(blank).unwrap();

            // write out a blank line, then a line with the new catalog year
            let title = {
                let mut v = Vec::new();
                v.push(format!("Catalog: {}", catalog));
                v.resize(longest_header, String::from(""));
                v
            };
            wtr.write_record(title).unwrap();

            last_header = header.clone();
            wtr.write_record(header).unwrap();
        } else if last_requirements != requirements {
            if i != 0 {
                // write out a blank line, then a line with the new catalog year
                let blank = vec![""; longest_header];
                wtr.write_record(blank).unwrap();
            }

            // write out a blank line, then a line with the new catalog year
            let title = {
                let mut v = Vec::new();
                v.push(format!("Catalog: {}", catalog));
                v.push(emphasis_req_names.join(" & "));
                v.resize(longest_header, String::from(""));
                v
            };
            wtr.write_record(title).unwrap();

            last_requirements = requirements.clone();
            // last_catalog = catalog.clone();
            wtr.write_record(header).unwrap();
        }

        data.resize(longest_header, String::from(""));

        wtr.write_record(data).unwrap();
    }

    wtr.flush().unwrap();
}

fn print_as_html(_opts: &Opts, results: Vec<MappedResult>) -> () {
    #[derive(Default)]
    struct Table {
        caption: String,
        header: Vec<String>,
        rows: Vec<Vec<String>>,
    }

    let grouped: HashMap<_, _> = results
        .into_iter()
        .map(|res| {
            (
                (
                    // res.catalog.clone(),
                    res.requirements.clone(),
                    res.emphasis_req_names.clone(),
                    res.header.clone(),
                ),
                res,
            )
        })
        .into_group_map();

    let grouped: BTreeMap<_, _> = grouped.iter().collect();

    let tables: Vec<Table> = grouped
        .into_iter()
        .map(
            |((_requirements, emphasis_req_names, header), group)| {
                let mut current_table: Table = Table::default();

                let catalogs = group.iter().map(|res| res.catalog.clone()).collect::<BTreeSet<_>>();
                let catalog = catalogs.into_iter().collect::<Vec<_>>().join(", ");

                // write out a blank line, then a line with the new catalog year
                current_table.caption = if !emphasis_req_names.is_empty() {
                    format!(
                        "Catalog: {}; Emphases: {}",
                        catalog,
                        emphasis_req_names.join(" & ")
                    )
                } else {
                    format!("Catalog: {}", catalog)
                };

                current_table.header = header.clone();

                current_table.rows = group
                    .iter()
                    .map(|result| {
                        let MappedResult { data, .. } = result;

                        let data = if data.len() != current_table.header.len() {
                            let mut d = data.clone();
                            d.resize(current_table.header.len(), String::from(""));
                            d
                        } else {
                            data.clone()
                        };

                        data
                    })
                    .collect();

                current_table
            },
        )
        .collect();

    println!(r#"<meta charset="utf-8">"#);

    for table in tables {
        if !table.caption.is_empty() {
            println!("<h2>{}</h2>", table.caption);
        }
        println!("<table>");
        println!("<thead>");
        println!("<tr>");
        for th in table.header {
            println!("<th>{}</th>", th);
        }
        println!("</tr>");
        println!("</thead>");

        println!("<tbody>");
        for tr in table.rows {
            println!("<tr>");
            for td in tr {
                let attrs = if !td.contains("✗") && !td.trim().is_empty() {
                    "class=\"passing\""
                } else {
                    "class=\"not-passing\""
                };
                println!(
                    "<td {}>{}</td>",
                    attrs,
                    askama_escape::escape(&td, askama_escape::Html)
                );
            }
            println!("</tr>");
        }
        println!("</tbody>");
        println!("</table>")
    }
}
