	if (cell->type == ID($demux))
	{
		std::vector<int> a = importDefSigSpec(cell->getPort(ID::A), timestep);
		std::vector<int> s = importDefSigSpec(cell->getPort(ID::S), timestep);
		std::vector<int> y = importDefSigSpec(cell->getPort(ID::Y), timestep);
		std::vector<int> yy = model_undef ? ez->vec_var(y.size()) : y;
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
			for (int i = 0; i < (1 << GetSize(s)); i++)
			{
				std::vector<int> ss;
				for (int j = 0; j < GetSize(s); j++) {
					if (i & 1 << j)
						ss.push_back(s[j]);
					else
						ss.push_back(ez->NOT(s[j]));
				}
				int sss = ez->expression(ezSAT::OpAnd, ss);

				for (int j = 0; j < GetSize(a); j++) {
					ez->SET(ez->AND(sss, a[j]), yy.at(i * GetSize(a) + j));
				}

				if (model_undef)
				{
					int s0 = ez->expression(ezSAT::OpOr, ez->vec_and(ez->vec_not(ss), ez->vec_not(undef_s)));
					int us = ez->AND(ez->NOT(s0), ez->expression(ezSAT::OpOr, undef_s));
					for (int j = 0; j < GetSize(a); j++) {
						int a0 = ez->AND(ez->NOT(a[j]), ez->NOT(undef_a[j]));
						int yX = ez->AND(ez->OR(us, undef_a[j]), ez->NOT(ez->OR(s0, a0)));
						ez->SET(yX, undef_y.at(i * GetSize(a) + j));
					}
				}
			}
			if (model_undef)
				undefGating(y, yy, undef_y);
		}
		return true;
	}
