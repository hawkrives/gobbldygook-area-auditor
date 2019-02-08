use super::ReservedPairings;

#[derive(Debug, Clone, PartialEq)]
pub struct RuleResult {
	pub detail: RuleResultDetails,
	pub reservations: ReservedPairings,
	pub status: RuleStatus,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RequirementResult {}

#[allow(dead_code)]
#[derive(Debug, Clone, PartialEq)]
pub enum RuleResultDetails {
	Course,
	Requirement(RequirementResult),
	CountOf(Vec<Option<RuleResult>>),
	Both((Box<RuleResult>, Box<RuleResult>)),
	Either((Option<Box<RuleResult>>, Option<Box<RuleResult>>)),
	Given,
	Do,
}

impl RuleResult {
	pub fn fail(detail: &RuleResultDetails) -> RuleResult {
		RuleResult {
			detail: detail.clone(),
			reservations: ReservedPairings::new(),
			status: RuleStatus::Fail,
		}
	}

	pub fn is_pass(&self) -> bool {
		match self.status {
			RuleStatus::Pass => true,
			_ => false,
		}
	}

	#[allow(dead_code)]
	pub fn is_fail(&self) -> bool {
		match self.status {
			RuleStatus::Fail => true,
			_ => false,
		}
	}
}

#[derive(Hash, PartialEq, Eq, Debug, Clone)]
pub enum RuleStatus {
	Pass,
	Fail,
	#[allow(dead_code)]
	Skipped,
	#[allow(dead_code)]
	Pending,
}
