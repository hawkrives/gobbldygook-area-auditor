mod command;
mod compute;
mod operator;
mod parse;
mod print;
#[cfg(test)]
mod tests;

use crate::util;
pub use crate::value::SingleValue as Value;
pub use command::Command;
pub use operator::Operator;
use serde::de::Deserializer;
use serde::{Deserialize, Serialize};
use std::fmt;

#[derive(Debug, PartialEq, Serialize, Deserialize, Clone)]
pub struct Action {
	pub lhs: Command,
	pub op: Option<Operator>,
	pub rhs: Option<Value>,
}

#[derive(Debug, PartialEq, Serialize, Deserialize, Clone)]
pub struct LhsValueAction {
	#[serde(deserialize_with = "util::string_or_struct_parseerror")]
	pub lhs: Value,
	#[serde(default, deserialize_with = "option_operator")]
	pub op: Option<Operator>,
	#[serde(default, deserialize_with = "option_value")]
	pub rhs: Option<Value>,
}

impl fmt::Display for Action {
	fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
		match &self {
			Action {
				lhs,
				rhs: None,
				op: None,
			} => write!(f, "{}", lhs),
			Action {
				lhs,
				rhs: Some(rhs),
				op: Some(op),
			} => write!(f, "{} {} {}", lhs, op, rhs),
			_ => Err(fmt::Error),
		}
	}
}

pub fn option_operator<'de, D>(deserializer: D) -> Result<Option<Operator>, D::Error>
where
	D: Deserializer<'de>,
{
	#[derive(Deserialize)]
	struct Wrapper(#[serde(deserialize_with = "util::string_or_struct_parseerror")] Operator);

	let v = Option::deserialize(deserializer)?;
	Ok(v.map(|Wrapper(a)| a))
}

pub fn option_value<'de, D>(deserializer: D) -> Result<Option<Value>, D::Error>
where
	D: Deserializer<'de>,
{
	#[derive(Deserialize)]
	struct Wrapper(#[serde(deserialize_with = "util::string_or_struct_parseerror")] Value);

	let v = Option::deserialize(deserializer)?;
	Ok(v.map(|Wrapper(a)| a))
}
