use super::*;
use crate::traits::print::Print;

#[test]
fn serialize() {
	let data = Rule {
		course: "STAT 214".to_string(),
		..Default::default()
	};

	let expected_str = "---
course: STAT 214";

	let actual = serde_yaml::to_string(&data).unwrap();
	assert_eq!(actual, expected_str);
}

#[test]
fn serialize_expanded() {
	let data = Rule {
		course: "STAT 214".to_string(),
		term: Some("2014-4".to_string()),
		..Default::default()
	};

	let expected_str = "---
course: STAT 214
term: 2014-4
section: ~
year: ~
semester: ~
lab: ~
can_match_used: ~";

	let actual = serde_yaml::to_string(&data).unwrap();
	assert_eq!(actual, expected_str);

	let deserialized: Rule = serde_yaml::from_str(&actual).unwrap();
	assert_eq!(deserialized, data);
}

#[test]
fn deserialize_labelled() {
	let data = "---
course: STAT 214";

	let expected_struct = Rule {
		course: "STAT 214".to_string(),
		..Default::default()
	};

	let deserialized: Rule = serde_yaml::from_str(&data).unwrap();
	assert_eq!(deserialized, expected_struct);
}

#[test]
fn deserialize_expanded() {
	let data = "---
course: STAT 214
term: 2014-4
section: ~
year: ~
semester: ~
lab: ~
can_match_used: ~";

	let expected_struct = Rule {
		course: "STAT 214".to_string(),
		term: Some("2014-4".to_string()),
		..Default::default()
	};

	let deserialized: Rule = serde_yaml::from_str(&data).unwrap();
	assert_eq!(deserialized, expected_struct);
}

#[test]
fn pretty_print() {
	let input = Rule {
		course: "DEPT 111".into(),
		..Default::default()
	};
	let expected = "DEPT 111";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		semester: Some("Fall".to_string()),
		year: Some(2015),
		..Default::default()
	};
	let expected = "DEPT 111 (Fall 2015)";
	assert_eq!(expected, input.print().unwrap());

	// TODO: implement term parsing to get to this point `let expected = "DEPT 111 (Fall 2015)";`
	let input = Rule {
		course: "DEPT 111".into(),
		term: Some("2015-1".to_string()),
		..Default::default()
	};
	let expected = "DEPT 111 (2015-1)";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		semester: Some("Fall".to_string()),
		..Default::default()
	};
	let expected = "DEPT 111 (Fall)";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		year: Some(2015),
		..Default::default()
	};
	let expected = "DEPT 111 (2015-16)";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		section: Some("A".to_string()),
		..Default::default()
	};
	let expected = "DEPT 111A";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		lab: Some(true),
		..Default::default()
	};
	let expected = "DEPT 111 (Lab)";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		semester: Some("Fall".to_string()),
		year: Some(2015),
		lab: Some(true),
		..Default::default()
	};
	let expected = "DEPT 111 (Lab; Fall 2015)";
	assert_eq!(expected, input.print().unwrap());

	let input = Rule {
		course: "DEPT 111".into(),
		section: Some("A".to_string()),
		semester: Some("Fall".to_string()),
		year: Some(2015),
		lab: Some(true),
		term: None,
		can_match_used: None,
	};
	let expected = "DEPT 111A (Lab; Fall 2015)";
	assert_eq!(expected, input.print().unwrap());
}