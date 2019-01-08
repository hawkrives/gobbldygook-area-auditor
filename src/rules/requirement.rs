use crate::util;

#[derive(Debug, PartialEq, Serialize, Deserialize, Clone)]
pub struct RequirementRule {
    pub requirement: String,
    #[serde(default = "util::serde_false")]
    pub optional: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serialize() {
        let data = RequirementRule {
            requirement: String::from("Name"),
            optional: false,
        };
        let expected = "---\nrequirement: Name\noptional: false";

        let actual = serde_yaml::to_string(&data).unwrap();
        assert_eq!(actual, expected);
    }

    #[test]
    fn deserialize() {
        let data = "---\nrequirement: Name\noptional: false";
        let expected = RequirementRule {
            requirement: String::from("Name"),
            optional: false,
        };

        let actual: RequirementRule = serde_yaml::from_str(&data).unwrap();
        assert_eq!(actual, expected);
    }

    #[test]
    fn deserialize_with_defaults() {
        let data = "---\nrequirement: Name";
        let expected = RequirementRule {
            requirement: String::from("Name"),
            optional: false,
        };

        let actual: RequirementRule = serde_yaml::from_str(&data).unwrap();
        assert_eq!(actual, expected);
    }
}
