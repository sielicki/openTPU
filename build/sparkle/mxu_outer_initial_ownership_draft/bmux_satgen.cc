	if (cell->type == ID($bmux))
	{
		std::vector<int> a = importDefSigSpec(cell->getPort(ID::A), timestep);
		std::vector<int> s = importDefSigSpec(cell->getPort(ID::S), timestep);
		std::vector<int> y = importDefSigSpec(cell->getPort(ID::Y), timestep);
		std::vector<int> undef_a, undef_s, undef_y;

		if (model_undef)
		{
			undef_a = importUndefSigSpec(cell->getPort(ID::A), timestep);
			undef_s = importUndefSigSpec(cell->getPort(ID::S), timestep);
			undef_y = importUndefSigSpec(cell->getPort(ID::Y), timestep);
		}

		if (GetSize(s) == 0) {
			ez->vec_set(a, y);
			if (model_undef)
				ez->vec_set(undef_a, undef_y);
		} else {
			for (int i = GetSize(s)-1; i >= 0; i--)
			{
				std::vector<int> out = (i == 0) ? y : ez->vec_var(a.size() / 2);
				std::vector<int> yy = model_undef ? ez->vec_var(out.size()) : out;

				std::vector<int> a0(a.begin(), a.begin() + a.size() / 2);
				std::vector<int> a1(a.begin() + a.size() / 2, a.end());
				ez->assume(ez->vec_eq(ez->vec_ite(s.at(i), a1, a0), yy));

				if (model_undef)
				{
					std::vector<int> undef_out = (i == 0) ? undef_y : ez->vec_var(a.size() / 2);
					std::vector<int> undef_a0(undef_a.begin(), undef_a.begin() + a.size() / 2);
					std::vector<int> undef_a1(undef_a.begin() + a.size() / 2, undef_a.end());
					std::vector<int> unequal_ab = ez->vec_not(ez->vec_iff(a0, a1));
					std::vector<int> undef_ab = ez->vec_or(unequal_ab, ez->vec_or(undef_a0, undef_a1));
					std::vector<int> yX = ez->vec_ite(undef_s.at(i), undef_ab, ez->vec_ite(s.at(i), undef_a1, undef_a0));
					ez->assume(ez->vec_eq(yX, undef_out));
					undefGating(out, yy, undef_out);

					undef_a = undef_out;
				}

				a = out;
			}
		}
		return true;
	}
